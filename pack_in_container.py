#!/usr/bin/env python3
"""
在Ubuntu 20容器中运行构建过程
将构建结果输出到挂载目录
"""

import os
import sys
import argparse
import subprocess
import json
import shutil
from pathlib import Path
from datetime import datetime

# 导入APT包列表
from pack import APT


class ContainerBuilder:
    def __init__(
        self,
        image="ubuntu:20.04",
        mount_dir="./.output",
        logs_dir="./.output_logs",
        container_workspace="/workspace",
        container_output="output",
        container_logs="output_logs",
        build_image_name="kvcache-cxx-builder",
    ):
        self.image = image
        self.mount_dir = Path(mount_dir).resolve()
        self.logs_dir = Path(logs_dir).resolve()
        self.container_workspace = container_workspace
        self.container_output = Path(container_output).resolve()
        self.container_logs = Path(container_logs).resolve()
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

    def create_dockerfile(self):
        """创建Dockerfile"""
        # 生成APT安装指令
        apt_install_commands = []
        for package in APT:
            apt_install_commands.append(f"RUN apt-get install -y {package}")

        apt_installs = "\n".join(apt_install_commands)

        dockerfile_content = f'''FROM {self.image}

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 设置时区
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 更新包列表
RUN apt-get update

# 安装所有依赖包（每个包一个RUN指令）
{apt_installs}

# 清理apt缓存
RUN rm -rf /var/lib/apt/lists/*

# 创建工作目录
WORKDIR {self.container_workspace}

# 复制构建脚本和配置文件
COPY pack.py .

# 设置Python路径
ENV PYTHONPATH={self.container_workspace}

# 创建输出目录
RUN mkdir -p {self.container_output}

# 创建日志目录
RUN mkdir -p {self.container_logs}

# 设置构建环境变量，让后续构建能找到已安装的库
ENV PKG_CONFIG_PATH={self.container_output}/lib/pkgconfig:{self.container_output}/lib64/pkgconfig:$PKG_CONFIG_PATH
ENV LD_LIBRARY_PATH={self.container_output}/lib:{self.container_output}/lib64:$LD_LIBRARY_PATH
ENV PATH={self.container_output}/bin:$PATH
ENV CPPFLAGS="-I{self.container_output}/include $CPPFLAGS"
ENV LDFLAGS="-L{self.container_output}/lib -L{self.container_output}/lib64 $LDFLAGS"

# 默认执行构建脚本
CMD ["python3", "pack.py", "--install-prefix", "{self.container_output}", "--output-logs-dir", "{self.container_logs}"]
'''

        dockerfile_path = self.build_dir / "Dockerfile"
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)

        print(f"Dockerfile created at {dockerfile_path}")
        print(f"Included {len(APT)} APT packages")
        print(f"Install prefix set to: {self.container_output}")

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

        cmd = f"docker build {platform_arg} -t {self.build_image_name} {self.build_dir}"
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

        # 运行容器，挂载输出目录，使用--rm自动删除
        docker_cmd = f"docker run --rm{platform_arg}{proxy_args} --mount type=bind,source={self.mount_dir},target={self.container_output} --mount type=bind,source={self.logs_dir},target={self.container_logs} --privileged {self.build_image_name}"

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
        cleanup_cmd = f"docker rmi {self.build_image_name} 2>/dev/null || true"
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
            f.write(f"Output Directory: {self.mount_dir}\n")
            f.write(f"Logs Directory: {self.logs_dir}\n\n")

            # 检查构建报告是否存在
            report_json = self.mount_dir / "build_report.json"
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
    parser = argparse.ArgumentParser(
        description="Build packages in Ubuntu 20 container"
    )
    parser.add_argument("--image", default="ubuntu:20.04", help="Docker base image")
    parser.add_argument(
        "--mount-dir", default="./.output", help="Local output directory to mount"
    )
    parser.add_argument(
        "--logs-dir", default="./.output_logs", help="Local logs directory to mount"
    )
    parser.add_argument(
        "--keep-image", action="store_true", help="Keep Docker image after build"
    )

    args = parser.parse_args()

    # 检查Docker是否可用
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
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
    print(f"Base image: {args.image}")
    print(f"Output directory: {os.path.abspath(args.mount_dir)}")
    print(f"Logs directory: {os.path.abspath(args.logs_dir)}")

    builder = ContainerBuilder(
        image=args.image, mount_dir=args.mount_dir, logs_dir=args.logs_dir
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
