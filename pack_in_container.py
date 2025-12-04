#!/usr/bin/env python3
"""
在Docker容器中运行构建过程
支持多种系统镜像和系统名称参数
将构建结果输出到挂载目录

使用示例:
  python3 pack_in_container.py                        # 自动检测当前系统
  python3 pack_in_container.py --system-name ubuntu20.04
  python3 pack_in_container.py --system-name ubuntu22.04
  python3 pack_in_container.py --system-name manylinux_2014
  python3 pack_in_container.py --system-name ubuntu20.04 --image custom:image  # 自定义镜像
"""

import os
import sys
import argparse
import subprocess
import json
import shutil
from pathlib import Path
from datetime import datetime

# 导入系统包配置
from pack import SYSLIBS


def get_sudo_prefix():
    """获取sudo命令前缀，如果不是root用户则返回'sudo -E '，否则返回空字符串"""
    # 检查是否为root用户
    if os.getuid() == 0:
        return ""
    else:
        return "sudo -E "


def get_docker_command(command):
    """构造docker命令，非root用户时添加sudo -E前缀"""
    sudo_prefix = get_sudo_prefix()
    return f"{sudo_prefix}{command}"

SYSNAME_IMAGE_MAP = {
    "ubuntu20.04": "ubuntu:20.04",
    "ubuntu22.04": "ubuntu:22.04",
    "manylinux_2014": {
        "amd64": "dockcross/manylinux2014-x64",
        "arm64": "dockcross/manylinux2014-aarch64",
    },
    "manylinux_2_28": {
        "amd64": "dockcross/manylinux_2_28-x64",
        "arm64": "dockcross/manylinux_2_28-aarch64",
    },
}


def detect_architecture():
    """检测当前系统架构"""
    import platform

    machine = platform.machine().lower()

    # 标准化架构名称
    if machine in ["x86_64", "amd64"]:
        return "amd64"
    elif machine in ["aarch64", "arm64"]:
        return "arm64"
    elif machine in ["armv7l", "armv6l"]:
        return "arm"
    else:
        print(f"Warning: Unknown architecture '{machine}', defaulting to amd64")
        return "amd64"


def get_image_for_system(system_name, arch=None):
    """根据系统名称和架构获取Docker镜像"""
    if arch is None:
        arch = detect_architecture()

    print(f"Getting image for system: {system_name}, architecture: {arch}")

    if system_name not in SYSNAME_IMAGE_MAP:
        raise ValueError(
            f"Unknown system name: {system_name}. Available options: {list(SYSNAME_IMAGE_MAP.keys())}"
        )

    image_config = SYSNAME_IMAGE_MAP[system_name]

    # 如果是字符串，直接返回（适用于ubuntu等）
    if isinstance(image_config, str):
        return image_config

    # 如果是字典，根据架构选择（适用于manylinux等）
    if isinstance(image_config, dict):
        if arch in image_config:
            return image_config[arch]
        else:
            available_archs = list(image_config.keys())
            raise ValueError(
                f"Architecture '{arch}' not supported for system '{system_name}'. "
                f"Available architectures: {available_archs}"
            )

    raise ValueError(f"Invalid image configuration for system '{system_name}'")


def detect_system_name():
    """自动检测当前系统名称"""
    import platform
    import re

    # 获取系统信息
    system = platform.system().lower()

    if system == "linux":
        try:
            # 尝试读取 /etc/os-release
            with open("/etc/os-release", "r") as f:
                content = f.read()

            # 查找 ID 和 VERSION_ID
            id_match = re.search(r'^ID=(["\']?)([^"\']+)\1', content, re.MULTILINE)
            version_match = re.search(
                r'^VERSION_ID=(["\']?)([^"\']+)\1', content, re.MULTILINE
            )

            if id_match:
                os_id = id_match.group(2).lower()
                version_id = version_match.group(2) if version_match else ""

                # 根据发行版和版本返回对应的系统名称
                if os_id == "ubuntu":
                    if version_id.startswith("20.04"):
                        return "ubuntu20.04"
                    elif version_id.startswith("22.04"):
                        return "ubuntu22.04"
                    else:
                        # 默认返回最新的Ubuntu版本
                        return "ubuntu22.04"
                elif os_id in ["centos", "rhel", "fedora"]:
                    # 对于基于RPM的系统，默认使用manylinux
                    return "manylinux_2014"

        except (FileNotFoundError, IOError):
            pass

        # 如果无法检测到具体版本，尝试其他方法
        try:
            # 尝试使用 lsb_release
            result = subprocess.run(
                ["lsb_release", "-si"], capture_output=True, text=True, check=True
            )
            distro = result.stdout.strip().lower()

            if "ubuntu" in distro:
                # 获取版本号
                version_result = subprocess.run(
                    ["lsb_release", "-sr"], capture_output=True, text=True, check=True
                )
                version = version_result.stdout.strip()

                if version.startswith("20.04"):
                    return "ubuntu20.04"
                elif version.startswith("22.04"):
                    return "ubuntu22.04"
                else:
                    return "ubuntu22.04"

        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # 如果检测失败，返回默认值
    print(
        "Warning: Could not detect system automatically, using ubuntu22.04 as default"
    )
    return "ubuntu22.04"


class ContainerBuilder:
    def __init__(
        self,
        system_name,
        image=None,
        arch=None,
        mount_dir="./.output",
        logs_dir="./.output_logs",
        container_workspace="/workspace",
        build_image_name="kvcache-cxx-builder",
    ):
        self.system_name = system_name
        self.arch = arch or detect_architecture()

        # 如果没有指定镜像，从映射表中获取
        if image is None:
            self.image = get_image_for_system(system_name, self.arch)
        else:
            self.image = image

        self.mount_dir = Path(mount_dir).resolve()
        self.logs_dir = Path(logs_dir).resolve()
        self.container_workspace = container_workspace
        self.container_name = (
            f"kvcache-builder-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        self.build_image_name = build_image_name
        self.build_dir = Path(".img_build")  # 构建目录

        # 确保挂载目录存在
        self.mount_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        # 确保构建目录存在
        self.build_dir.mkdir(exist_ok=True)

    def run_command(self, cmd: str, check: bool = True) -> int:
        """执行shell命令"""
        print(f"Running: {cmd}")

        # 使用os.system执行命令
        result = os.system(cmd)

        if check and result != 0:
            raise subprocess.CalledProcessError(result, cmd)

        return result

    def prepare_build_context(self):
        """准备构建上下文，复制必要文件到构建目录"""
        print("Preparing build context...")

        # 清理构建目录
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(exist_ok=True)

        # 复制必要文件到构建目录
        shutil.copy("pack.py", self.build_dir / "pack.py")

        print(f"Build context prepared in {self.build_dir}")

    def get_system_packages_config(self):
        """根据系统名称获取包配置"""
        for syslib in SYSLIBS:
            if self.system_name in syslib["system"]:
                return syslib

        # 如果没有找到精确匹配，尝试部分匹配
        for syslib in SYSLIBS:
            for system in syslib["system"]:
                if system in self.system_name or self.system_name in system:
                    print(f"Using partial match: {system} for {self.system_name}")
                    return syslib

        print(f"Warning: No package configuration found for system: {self.system_name}")
        return None

    def create_dockerfile(self):
        """创建Dockerfile"""
        # 获取系统包配置
        pkg_config = self.get_system_packages_config()

        if not pkg_config:
            # 如果没有配置，使用Ubuntu默认配置
            print(
                f"Warning: No package config for {self.system_name}, using ubuntu defaults"
            )
            pkg_config = {
                "package_manager": "apt",
                "packages": [
                    "build-essential",
                    "cmake",
                    "git",
                    "python3",
                    "python3-pip",
                ],
            }

        packages = pkg_config.get("packages", [])
        package_manager = pkg_config.get("package_manager", "apt")

        # 根据包管理器类型设置命令
        if package_manager == "apt":
            update_command = "apt-get update"
            install_command = "apt-get install -y"
        elif package_manager == "yum":
            update_command = "yum update -y"
            install_command = "yum install -y"
        elif package_manager == "dnf":
            update_command = "dnf update -y"
            install_command = "dnf install -y"
        elif package_manager == "apk":
            update_command = "apk update"
            install_command = "apk add"
        else:
            print(
                f"Warning: Unknown package manager: {package_manager}, using apt defaults"
            )
            update_command = "apt-get update"
            install_command = "apt-get install -y"

        # 生成包安装指令
        package_install_commands = []

        # 分批安装包，避免命令行过长
        batch_size = 10
        for i in range(0, len(packages), batch_size):
            batch = packages[i : i + batch_size]
            if batch:
                package_install_commands.append(
                    f"RUN {install_command} {' '.join(batch)}"
                )

        package_installs = "\n".join(package_install_commands)

        # 根据包管理器类型设置不同的环境变量和基础命令
        if package_manager == "apt":
            env_setup = """# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 设置时区
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone"""

            update_and_cleanup = f"""# 更新包列表
RUN {update_command}

# 安装所有依赖包
{package_installs}

# 清理apt缓存
RUN rm -rf /var/lib/apt/lists/*"""

        elif package_manager == "yum":
            env_setup = """# 设置环境变量
ENV TZ=Asia/Shanghai"""

            update_and_cleanup = f"""# 更新包列表和安装基础工具
RUN {update_command}

# 安装所有依赖包
{package_installs}

# 清理yum缓存
RUN yum clean all"""

        elif package_manager == "dnf":
            env_setup = """# 设置环境变量
ENV TZ=Asia/Shanghai"""

            update_and_cleanup = f"""# 安装所有依赖包
{package_installs}

# 清理dnf缓存
RUN dnf clean all"""

        elif package_manager == "apk":
            env_setup = """# 设置环境变量
ENV TZ=Asia/Shanghai"""

            update_and_cleanup = f"""# 更新包列表
RUN {update_command}

# 安装所有依赖包
{package_installs}

# 清理apk缓存
RUN rm -rf /var/cache/apk/*"""

        else:
            # 默认情况
            env_setup = """# 设置环境变量
ENV TZ=Asia/Shanghai"""

            update_and_cleanup = f"""# 更新包列表
RUN {update_command}

# 安装所有依赖包
{package_installs}"""

        dockerfile_content = f'''FROM {self.image}

{env_setup}

{update_and_cleanup}

# 创建工作目录
WORKDIR {self.container_workspace}

# 复制构建脚本和配置文件
COPY pack.py .

# 设置Python路径
ENV PYTHONPATH={self.container_workspace}

# 默认执行构建脚本
CMD ["python3", "pack.py", "local", "--system-name", "{self.system_name}"]
'''

        dockerfile_path = self.build_dir / "Dockerfile"
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        print(f"Dockerfile created at {dockerfile_path}")
        print(f"Package manager: {package_manager}")
        print(f"Included {len(packages)} packages")
        print(f"System name: {self.system_name}")
        print(f"Command: python3 pack.py local --system-name {self.system_name}")

    def build_docker_image(self):
        """构建Docker镜像"""
        print(f"Building Docker image: {self.build_image_name}")

        # 准备构建上下文
        self.prepare_build_context()

        # 创建Dockerfile
        self.create_dockerfile()

        # 构建镜像 - 支持多架构
        platform_arg = ""
        if "DOCKER_DEFAULT_PLATFORM" in os.environ:
            platform_arg = f"--platform {os.environ['DOCKER_DEFAULT_PLATFORM']}"
            print(f"Using platform: {os.environ['DOCKER_DEFAULT_PLATFORM']}")

        cmd = get_docker_command(f"docker build {platform_arg} -t {self.build_image_name} {self.build_dir}")
        self.run_command(cmd)

        print(f"Docker image {self.build_image_name} built successfully")

    def get_proxy_env_vars(self):
        """获取当前环境中的proxy环境变量"""
        proxy_vars = [
            "http_proxy",
            "https_proxy",
            "ftp_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "FTP_PROXY",
            "no_proxy",
            "NO_PROXY",
        ]

        env_args = []
        for var in proxy_vars:
            if var in os.environ:
                value = os.environ[var]
                env_args.append(f"-e {var}='{value}'")
                print(f"Found proxy variable: {var}={value}")

        return " ".join(env_args)

    def run_container(self):
        """运行容器执行构建"""
        print(f"Running container with image: {self.build_image_name}")

        # 获取proxy环境变量
        proxy_env = self.get_proxy_env_vars()
        proxy_args = f" {proxy_env}" if proxy_env else ""

        # 添加平台支持
        platform_arg = ""
        if "DOCKER_DEFAULT_PLATFORM" in os.environ:
            platform_arg = f" --platform {os.environ['DOCKER_DEFAULT_PLATFORM']}"

        # 运行容器，挂载输出目录到固定的output和output_logs目录
        docker_cmd = get_docker_command(f"docker run --rm{platform_arg}{proxy_args} --mount type=bind,source={self.mount_dir},target={self.container_workspace}/output --mount type=bind,source={self.logs_dir},target={self.container_workspace}/output_logs --privileged {self.build_image_name}")

        print(f"Docker command: {docker_cmd}")

        # 直接阻塞执行docker run
        result = os.system(docker_cmd)

        # 检查构建是否成功
        if result == 0:
            print("Container build completed successfully!")
            return True
        else:
            print(f"Container build failed with exit code: {result}")
            return False

    def cleanup_image(self):
        """清理Docker镜像"""
        cleanup_cmd = get_docker_command(f"docker rmi {self.build_image_name} 2>/dev/null || true")
        os.system(cleanup_cmd)
        print(f"Docker image {self.build_image_name} removed")

    def cleanup_build_dir(self):
        """清理构建目录"""
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
            print(f"Build directory {self.build_dir} removed")

    def build_and_run(self, cleanup_after=True):
        """完整的构建和运行流程"""
        try:
            # 构建镜像
            self.build_docker_image()

            # 运行容器
            success = self.run_container()

            # 生成总结报告
            self.generate_summary()

            if success:
                print(f"✅ Build completed successfully for {self.system_name}")
            else:
                print(f"❌ Build failed for {self.system_name}")

            return success

        except Exception as e:
            print(f"Build process failed: {e}")
            return False

        finally:
            if cleanup_after:
                self.cleanup_image()
                self.cleanup_build_dir()

    def generate_summary(self):
        """生成构建总结"""
        summary_file = self.mount_dir / "build_summary.txt"

        with open(summary_file, "w") as f:
            f.write("KV Cache C++ Packer Build Summary\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Build Time: {datetime.now()}\n")
            f.write(f"Build Image: {self.build_image_name}\n")
            f.write(f"Base Image: {self.image}\n")
            f.write(f"System Name: {self.system_name}\n")
            f.write(f"Architecture: {self.arch}\n")
            f.write(f"Output Directory: {self.mount_dir}\n")
            f.write(f"Logs Directory: {self.logs_dir}\n\n")

            # 检查构建报告是否存在
            report_json = self.logs_dir / "build_report.json"
            if report_json.exists():
                try:
                    with open(report_json, "r") as rf:
                        build_results = json.load(rf)

                    successful = sum(
                        1 for r in build_results.values() if r.get("success", False)
                    )
                    total = len(build_results)

                    f.write(
                        f"Build Results: {successful}/{total} packages successful\n\n"
                    )

                    f.write("Package Status:\n")
                    f.write("-" * 30 + "\n")
                    for package, result in build_results.items():
                        status = "✓" if result.get("success", False) else "✗"
                        f.write(
                            f"{status} {package}: {result.get('message', 'Unknown')}\n"
                        )

                except Exception as e:
                    f.write(f"Error reading build report: {e}\n")
            else:
                f.write("Build report not found\n")

            # 列出输出文件
            f.write("\n\nOutput Files:\n")
            f.write("-" * 20 + "\n")
            for item in sorted(self.mount_dir.iterdir()):
                if item.name != "build_summary.txt":
                    f.write(f"- {item.name}\n")

        print(f"Build summary saved to {summary_file}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Build packages in Docker container")
    parser.add_argument(
        "--image",
        help="Docker base image (optional, auto-detected from system-name if not specified)",
    )
    parser.add_argument(
        "--arch",
        help="Target architecture (amd64, arm64). If not specified, auto-detect current system architecture",
    )
    parser.add_argument(
        "--mount-dir", default="./.output", help="Local output directory to mount"
    )
    parser.add_argument(
        "--logs-dir", default="./.output_logs", help="Local logs directory to mount"
    )
    parser.add_argument(
        "--keep-image", action="store_true", help="Keep Docker image after build"
    )
    parser.add_argument(
        "--system-name",
        help="System name (e.g., ubuntu20.04, manylinux_2014). If not specified, auto-detect current system",
    )

    args = parser.parse_args()

    # 如果没有指定 system_name，自动检测
    if not args.system_name:
        print("Auto-detecting system name...")
        system_name = detect_system_name()
        print(f"Detected system: {system_name}")
    else:
        system_name = args.system_name

    # 如果没有指定架构，自动检测
    if not args.arch:
        arch = detect_architecture()
        print(f"Auto-detected architecture: {arch}")
    else:
        arch = args.arch

    # 验证系统名称是否支持
    if system_name not in SYSNAME_IMAGE_MAP:
        print(f"Error: Unknown system name '{system_name}'")
        print(f"Available options: {list(SYSNAME_IMAGE_MAP.keys())}")
        sys.exit(1)

    # 如果没有指定镜像，验证系统和架构组合是否有效
    if not args.image:
        try:
            test_image = get_image_for_system(system_name, arch)
            print(f"Will use image: {test_image}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    # 检查Docker是否可用
    try:
        # 检查Docker是否可用，根据权限使用sudo
        docker_version_cmd = get_docker_command("docker --version").strip().split()
        subprocess.run(docker_version_cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Docker is not available. Please install Docker first.")
        sys.exit(1)

    # 检查必要文件是否存在
    required_files = ["pack.py"]
    for file in required_files:
        if not os.path.exists(file):
            print(f"Error: Required file {file} not found")
            sys.exit(1)

    print("Starting containerized build process...")
    print(f"System name: {system_name}")
    print(f"Architecture: {arch}")
    print(f"Output directory: {os.path.abspath(args.mount_dir)}")
    print(f"Logs directory: {os.path.abspath(args.logs_dir)}")

    builder = ContainerBuilder(
        system_name=system_name,
        image=args.image,
        arch=arch,
        mount_dir=args.mount_dir,
        logs_dir=args.logs_dir,
    )

    success = builder.build_and_run(cleanup_after=not args.keep_image)

    if success:
        print("\n🎉 Build completed successfully!")
        print(f"📁 Results are available in: {os.path.abspath(args.mount_dir)}")
        print("📋 Check build_summary.txt for detailed results")
    else:
        print("\n❌ Build failed. Check the logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
