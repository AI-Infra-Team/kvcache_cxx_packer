#!/usr/bin/env python3
"""
本地多平台构建脚本
使用Docker构建不同系统版本的包
"""

import os
import sys
import subprocess
import argparse
import json
from pathlib import Path

# 系统配置，与CI保持一致
PLATFORM_CONFIGS = {
    "ubuntu20.04": {
        "image": "ubuntu:20.04",
        "system_name": "ubuntu20.04",
        "setup_commands": [
            "apt-get update",
            "apt-get install -y python3 python3-pip sudo wget curl git build-essential",
            "ln -fs /usr/share/zoneinfo/UTC /etc/localtime",
            "DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata",
        ],
    },
    "ubuntu22.04": {
        "image": "ubuntu:22.04",
        "system_name": "ubuntu22.04",
        "setup_commands": [
            "apt-get update",
            "apt-get install -y python3 python3-pip sudo wget curl git build-essential",
            "ln -fs /usr/share/zoneinfo/UTC /etc/localtime",
            "DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata",
        ],
    },
    "manylinux_2014": {
        "image": "quay.io/pypa/manylinux_2014_x86_64",
        "system_name": "manylinux_2014",
        "setup_commands": [
            "yum update -y",
            "yum install -y python3 python3-pip sudo wget curl git",
            "yum groupinstall -y 'Development Tools'",
            # 如果没有python3，创建链接
            "if ! command -v python3 &> /dev/null; then ln -s /usr/bin/python /usr/bin/python3; fi",
        ],
    },
    "manylinux_2_24": {
        "image": "quay.io/pypa/manylinux_2_24_x86_64",
        "system_name": "manylinux_2_24",
        "setup_commands": [
            "yum update -y",
            "yum install -y python3 python3-pip sudo wget curl git",
            "yum groupinstall -y 'Development Tools'",
        ],
    },
}


def run_command(cmd, check=True):
    """运行shell命令"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result.returncode


def build_for_platform(platform_name, config, workspace_dir, output_dir):
    """为指定平台构建包"""
    print(f"\n=== Building for {platform_name} ===")

    image = config["image"]
    system_name = config["system_name"]
    setup_commands = config["setup_commands"]

    # 确保输出目录存在
    platform_output_dir = output_dir / platform_name
    platform_output_dir.mkdir(parents=True, exist_ok=True)

    # 构建Docker命令
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-it",
        "--privileged",  # 某些构建过程可能需要特权
        f"--volume={workspace_dir}:/workspace",
        f"--volume={platform_output_dir}:/output_host",
        f"--workdir=/workspace",
        f"--env=SYSTEM_NAME={system_name}",
        image,
        "bash",
        "-c",
    ]

    # 构建脚本内容
    script_content = []

    # 添加设置命令
    script_content.extend(setup_commands)

    # 添加构建命令
    script_content.extend(
        [
            "echo 'System setup completed'",
            "echo 'Building for system: $SYSTEM_NAME'",
            "echo 'Architecture: $(uname -m)'",
            "python3 pack.py build",
            "echo 'Build completed, copying artifacts...'",
            "cp -v output_*.tar.gz /output_host/ 2>/dev/null || echo 'No tar.gz files to copy'",
            "cp -rv output_logs /output_host/ 2>/dev/null || echo 'No output_logs to copy'",
            "ls -la /output_host/",
        ]
    )

    # 将所有命令连接成一个脚本
    full_script = " && ".join(script_content)
    docker_cmd.append(full_script)

    try:
        # 执行Docker构建
        cmd_str = " ".join(docker_cmd[:-1]) + f' "{docker_cmd[-1]}"'
        result = run_command(cmd_str, check=False)

        if result == 0:
            print(f"✅ Successfully built for {platform_name}")
            # 检查生成的文件
            artifacts = list(platform_output_dir.glob("*.tar.gz"))
            if artifacts:
                print(f"Generated artifacts: {[a.name for a in artifacts]}")
            else:
                print("⚠️  No artifacts generated")
        else:
            print(f"❌ Build failed for {platform_name}")

        return result == 0

    except Exception as e:
        print(f"❌ Error building for {platform_name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Local multi-platform build script")
    parser.add_argument(
        "--platforms",
        nargs="+",
        choices=list(PLATFORM_CONFIGS.keys()) + ["all"],
        default=["all"],
        help="Platforms to build for",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("multi_platform_builds"),
        help="Output directory for platform-specific builds",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace directory (current directory by default)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without executing them"
    )

    args = parser.parse_args()

    # 检查Docker是否可用
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker is not available. Please install Docker first.")
        sys.exit(1)

    # 确定要构建的平台
    if "all" in args.platforms:
        platforms_to_build = list(PLATFORM_CONFIGS.keys())
    else:
        platforms_to_build = args.platforms

    print(f"Building for platforms: {platforms_to_build}")
    print(f"Workspace: {args.workspace}")
    print(f"Output directory: {args.output_dir}")

    if args.dry_run:
        print("\n=== DRY RUN MODE ===")
        for platform in platforms_to_build:
            config = PLATFORM_CONFIGS[platform]
            print(f"\nPlatform: {platform}")
            print(f"  Image: {config['image']}")
            print(f"  System Name: {config['system_name']}")
            print(f"  Setup Commands: {config['setup_commands']}")
        return

    # 创建输出目录
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 构建所有平台
    results = {}
    for platform in platforms_to_build:
        config = PLATFORM_CONFIGS[platform]
        success = build_for_platform(platform, config, args.workspace, args.output_dir)
        results[platform] = success

    # 输出总结
    print("\n=== Build Summary ===")
    successful = 0
    for platform, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{platform}: {status}")
        if success:
            successful += 1

    print(f"\nTotal: {successful}/{len(results)} platforms built successfully")

    if successful > 0:
        print(f"\nArtifacts saved to: {args.output_dir}")
        # 列出所有生成的文件
        for platform_dir in args.output_dir.iterdir():
            if platform_dir.is_dir():
                artifacts = list(platform_dir.glob("*.tar.gz"))
                if artifacts:
                    print(f"  {platform_dir.name}: {[a.name for a in artifacts]}")

    # 如果有失败的构建，返回非零退出码
    if successful < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
