#!/usr/bin/env python3
"""
KV Cache C++ Packer
自动拉取、编译、安装脚本，用于构建所有依赖包
"""

import os
import sys
import subprocess
import json
import shutil
import logging
import glob
import platform
import re
from pathlib import Path
from typing import Dict, List


# 固定目录配置
BUILD_DIR = "build"
OUTPUT_LOGS_DIR = "output_logs"
OUTPUT_DIR = "output"
SYSTEM_INSTALL_PREFIX = "/usr/local"


ENV_IMAGES = [
    # Docker镜像列表，用于参考（实际使用在CI配置中）
    "ubuntu:20.04",
    "ubuntu:22.04",
    "quay.io/pypa/manylinux_2014_x86_64",
    "quay.io/pypa/manylinux_2_24_x86_64",
]
# 包配置
PACKS = {
    "https://github.com/protocolbuffers/protobuf": {
        "branch": "v3.21.12",
        "c++": 17,
        "build_type": "Release",
        "cmakename": "Protobuf",  # CMake中的包名
        "define": [
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
            ["protobuf_BUILD_TESTS", "OFF"],
            ["protobuf_BUILD_EXAMPLES", "OFF"],
            ["protobuf_MSVC_STATIC_RUNTIME", "OFF"],
        ],
    },
    "https://github.com/grpc/grpc": {
        "branch": "v1.50.2",
        "c++": 17,
        "dependencies": ["protobuf"],
        "build_type": "Release",
        "cmakename": "gRPC",  # CMake中的包名
        "define": [
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
            ["gRPC_BUILD_TESTS", "OFF"],
            ["gRPC_BUILD_CSHARP_EXT", "OFF"],
            ["gRPC_BUILD_GRPC_CSHARP_PLUGIN", "OFF"],
            ["gRPC_BUILD_GRPC_NODE_PLUGIN", "OFF"],
            ["gRPC_BUILD_GRPC_OBJECTIVE_C_PLUGIN", "OFF"],
            ["gRPC_BUILD_GRPC_PHP_PLUGIN", "OFF"],
            ["gRPC_BUILD_GRPC_PYTHON_PLUGIN", "OFF"],
            ["gRPC_BUILD_GRPC_RUBY_PLUGIN", "OFF"],
        ],
    },
    "https://github.com/AI-Infra-Team/etcd-cpp-apiv3": {
        "branch": "master",
        "c++": 17,
        "dependencies": ["protobuf", "grpc"],
        "build_type": "Release",
        "define": [
            ["BUILD_STATIC_LIBS", "ON"],
            ["BUILD_SHARED_LIBS", "OFF"],
        ],
    },
    "https://github.com/AI-Infra-Team/gflags": {
        "branch": "master",
        "c++": 17,
        "build_type": "Release",
        "define": [
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
            ["BUILD_gflags_LIB", "ON"],
        ],
    },
    "https://github.com/AI-Infra-Team/glog": {
        "branch": "v0.6.0",
        "c++": 17,
        "dependencies": ["gflags"],
        "build_type": "Release",
        "define": [
            ["WITH_GFLAGS", "ON"],
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
        ],
    },
    # "https://github.com/AI-Infra-Team/googletest": {
    #     "branch": "main",
    # },
    "https://github.com/AI-Infra-Team/jsoncpp": {
        "branch": "master",
        "c++": 17,
        "define": [
            ["BUILD_SHARED_LIBS", "OFF"],
            ["BUILD_STATIC_LIBS", "ON"],
            ["BUILD_OBJECT_LIBS", "OFF"],
            ["CMAKE_BUILD_TYPE", "Release"],
        ],
    },
    "https://github.com/AI-Infra-Team/rdma-core": {
        "branch": "master",
        "c++": 17,
        "define": [
            ["NO_PYVERBS", "ON"],
            ["BUILD_SHARED_LIBS", "ON"],
            ["BUILD_STATIC_LIBS", "OFF"],
            ["BUILD_TESTING", "OFF"],
            ["BUILD_EXAMPLES", "OFF"],
            ["BUILD_EXAMPLES", "OFF"],
            ["NO_MAN_PAGES", "ON"],
        ],
    },
    "https://github.com/AI-Infra-Team/yalantinglibs": {
        "branch": "main",
        "c++": 20,
        "dependencies": ["rdma-core"],
        "define": [
            ["GENERATE_BENCHMARK_DATA", "OFF"],
            ["BUILD_EXAMPLES", "OFF"],
            ["BUILD_BENCHMARK", "OFF"],
            ["BUILD_TESTING", "OFF"],
            ["COVERAGE_TEST", "OFF"],
            ["BUILD_UNIT_TESTS", "OFF"],
        ],
    },
}

# 系统依赖包配置
SYSLIBS = [
    {
        "system": [
            "ubuntu20.04",
            "ubuntu22.04",
        ],
        "package_manager": "apt",
        "packages": [
            # 基础构建工具
            "build-essential",
            "cmake",
            "git",
            "pkg-config",
            "autoconf",
            "automake",
            "libtool",
            "wget",
            "curl",
            "python3",
            "python3-pip",
            # 开发库
            "libssl-dev",
            "zlib1g-dev",
            "ca-certificates",
            # 项目特定依赖
            "libprotobuf-dev",
            "protobuf-compiler-grpc",
            "libgrpc++-dev",
            "libgrpc-dev",
            "libunwind-dev",
            "gcc-10",
            "g++-10",
            "libcpprest-dev",
            "libnl-3-dev",
            "libnl-route-3-dev",
        ],
    },
    {
        "system": [
            "manylinux_2014",
        ],
        "package_manager": "yum",
        "packages": [
            # 基础构建工具
            "gcc",
            "gcc-c++",
            "make",
            "cmake3",
            "git",
            "pkgconfig",
            "autoconf",
            "automake",
            "libtool",
            "wget",
            "curl",
            # 开发库
            "openssl-devel",
            "zlib-devel",
            # 网络和构建工具
            "which",
            "patch",
            "diffutils",
            "tar",
            "gzip",
            "bzip2",
            "xz",
            # 编译相关
            "libstdc++-devel",
            "glibc-devel",
            # 其他基础依赖
            "flex",
            "bison",
        ],
    },
]

DYNAMIC_COPY = [
    # "*grpc*.so*",
    # "*protobuf*.so*",
    "*unwind*.so*",
    "libssl.so.1.1",
    "libcrypto.so.1.1",
    "libprotobuf.so.17.0.0",
]
DYNAMIC_COPY_RENAME = [
    ("libgrpc++.so.1.16.1", "libgrpc++.so"),
    ("libgrpc.so.6.0.0", "libgrpc.so"),
    ("libgrpc.so.6.0.0", "libgrpc.so.6"),
    ("libssl.so.1.1", "libssl.so"),
    ("libcrypto.so.1.1", "libcrypto.so"),
    ("libprotobuf.so.17.0.0", "libprotobuf.so"),
    ("libprotobuf.so.17.0.0", "libprotobuf.so.17"),
]
CREATE_LIB_CMAKE_CONFIG = {
    "grpc++": """# Generated by kvcache_cxx_packer
# gRPC CMake Configuration File

# Compute the installation prefix relative to this file
get_filename_component(_IMPORT_PREFIX "${CMAKE_CURRENT_LIST_FILE}" PATH)
get_filename_component(_IMPORT_PREFIX "${_IMPORT_PREFIX}" PATH)
get_filename_component(_IMPORT_PREFIX "${_IMPORT_PREFIX}" PATH)
if(_IMPORT_PREFIX STREQUAL "/")
  set(_IMPORT_PREFIX "")
endif()

# Set the include directories
set(gRPC_INCLUDE_DIRS "${_IMPORT_PREFIX}/include")

# Set the library directories
set(gRPC_LIBRARY_DIRS "${_IMPORT_PREFIX}/lib")

# Find the libraries using relative paths
find_library(gRPC_LIBRARY NAMES grpc PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(gRPC_CPP_LIBRARY NAMES grpc++ PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(gRPC_UNSECURE_LIBRARY NAMES grpc_unsecure PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(gRPC_CPP_UNSECURE_LIBRARY NAMES grpc++_unsecure PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)

# Find protobuf
find_library(PROTOBUF_LIBRARY NAMES protobuf PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(PROTOC_LIBRARY NAMES protoc PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)

# Find additional dependencies
find_library(CARES_LIBRARY NAMES cares PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(ADDRESS_SORTING_LIBRARY NAMES address_sorting PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(RE2_LIBRARY NAMES re2 PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(UPB_LIBRARY NAMES upb PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(ABSL_BASE_LIBRARY NAMES absl_base PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(ABSL_STRINGS_LIBRARY NAMES absl_strings PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)

# Set the found variables
set(gRPC_FOUND TRUE)
set(gRPC_LIBRARIES ${gRPC_LIBRARY} ${gRPC_CPP_LIBRARY})

# Create imported targets
if(NOT TARGET gRPC::grpc)
    add_library(gRPC::grpc SHARED IMPORTED)
    set_target_properties(gRPC::grpc PROPERTIES
        IMPORTED_LOCATION "${gRPC_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
    )
endif()

if(NOT TARGET gRPC::grpc++)
    add_library(gRPC::grpc++ SHARED IMPORTED)
    set_target_properties(gRPC::grpc++ PROPERTIES
        IMPORTED_LOCATION "${gRPC_CPP_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
        INTERFACE_LINK_LIBRARIES "gRPC::grpc"
    )
endif()

if(gRPC_UNSECURE_LIBRARY AND NOT TARGET gRPC::grpc_unsecure)
    add_library(gRPC::grpc_unsecure SHARED IMPORTED)
    set_target_properties(gRPC::grpc_unsecure PROPERTIES
        IMPORTED_LOCATION "${gRPC_UNSECURE_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
    )
endif()

if(gRPC_CPP_UNSECURE_LIBRARY AND NOT TARGET gRPC::grpc++_unsecure)
    add_library(gRPC::grpc++_unsecure SHARED IMPORTED)
    set_target_properties(gRPC::grpc++_unsecure PROPERTIES
        IMPORTED_LOCATION "${gRPC_CPP_UNSECURE_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
        INTERFACE_LINK_LIBRARIES "gRPC::grpc_unsecure"
    )
endif()

# Set variables for compatibility
set(GRPC_INCLUDE_DIRS ${gRPC_INCLUDE_DIRS})
set(GRPC_LIBRARIES ${gRPC_LIBRARIES})
set(GRPC_FOUND ${gRPC_FOUND})

# Set the grpc_DIR for find_package
set(grpc_DIR "${_IMPORT_PREFIX}/lib/cmake/grpc")
set(gRPC_DIR "${_IMPORT_PREFIX}/lib/cmake/grpc")

# Clean up
set(_IMPORT_PREFIX)
""",
    "gRPC": """# Generated by kvcache_cxx_packer
# gRPC CMake Configuration File (Alternative naming)

# Compute the installation prefix relative to this file
get_filename_component(_IMPORT_PREFIX "${CMAKE_CURRENT_LIST_FILE}" PATH)
get_filename_component(_IMPORT_PREFIX "${_IMPORT_PREFIX}" PATH)
get_filename_component(_IMPORT_PREFIX "${_IMPORT_PREFIX}" PATH)
if(_IMPORT_PREFIX STREQUAL "/")
  set(_IMPORT_PREFIX "")
endif()

# Set the include directories
set(gRPC_INCLUDE_DIRS "${_IMPORT_PREFIX}/include")
set(GRPC_INCLUDE_DIRS "${_IMPORT_PREFIX}/include")

# Set the library directories
set(gRPC_LIBRARY_DIRS "${_IMPORT_PREFIX}/lib")
set(GRPC_LIBRARY_DIRS "${_IMPORT_PREFIX}/lib")

# Find the libraries using relative paths
find_library(gRPC_LIBRARY NAMES grpc PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(gRPC_CPP_LIBRARY NAMES grpc++ PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(gRPC_UNSECURE_LIBRARY NAMES grpc_unsecure PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(gRPC_CPP_UNSECURE_LIBRARY NAMES grpc++_unsecure PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)

# Find protobuf
find_library(PROTOBUF_LIBRARY NAMES protobuf PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(PROTOC_LIBRARY NAMES protoc PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)

# Find additional dependencies
find_library(CARES_LIBRARY NAMES cares PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(ADDRESS_SORTING_LIBRARY NAMES address_sorting PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(RE2_LIBRARY NAMES re2 PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(UPB_LIBRARY NAMES upb PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(ABSL_BASE_LIBRARY NAMES absl_base PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(ABSL_STRINGS_LIBRARY NAMES absl_strings PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)

# Set the found variables (both gRPC_ and GRPC_ prefixes for compatibility)
set(gRPC_FOUND TRUE)
set(GRPC_FOUND TRUE)
set(gRPC_LIBRARIES ${gRPC_LIBRARY} ${gRPC_CPP_LIBRARY})
set(GRPC_LIBRARIES ${gRPC_LIBRARY} ${gRPC_CPP_LIBRARY})

# Create imported targets
if(NOT TARGET gRPC::grpc)
    add_library(gRPC::grpc SHARED IMPORTED)
    set_target_properties(gRPC::grpc PROPERTIES
        IMPORTED_LOCATION "${gRPC_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
    )
endif()

if(NOT TARGET gRPC::grpc++)
    add_library(gRPC::grpc++ SHARED IMPORTED)
    set_target_properties(gRPC::grpc++ PROPERTIES
        IMPORTED_LOCATION "${gRPC_CPP_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
        INTERFACE_LINK_LIBRARIES "gRPC::grpc"
    )
endif()

if(gRPC_UNSECURE_LIBRARY AND NOT TARGET gRPC::grpc_unsecure)
    add_library(gRPC::grpc_unsecure SHARED IMPORTED)
    set_target_properties(gRPC::grpc_unsecure PROPERTIES
        IMPORTED_LOCATION "${gRPC_UNSECURE_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
    )
endif()

if(gRPC_CPP_UNSECURE_LIBRARY AND NOT TARGET gRPC::grpc++_unsecure)
    add_library(gRPC::grpc++_unsecure SHARED IMPORTED)
    set_target_properties(gRPC::grpc++_unsecure PROPERTIES
        IMPORTED_LOCATION "${gRPC_CPP_UNSECURE_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${gRPC_INCLUDE_DIRS}"
        INTERFACE_LINK_LIBRARIES "gRPC::grpc_unsecure"
    )
endif()

# Create additional targets with GRPC:: namespace for compatibility
if(NOT TARGET GRPC::grpc)
    add_library(GRPC::grpc ALIAS gRPC::grpc)
endif()

if(NOT TARGET GRPC::grpc++)
    add_library(GRPC::grpc++ ALIAS gRPC::grpc++)
endif()

# Set directory variables for find_package compatibility
set(gRPC_DIR "${_IMPORT_PREFIX}/lib/cmake/gRPC")
set(GRPC_DIR "${_IMPORT_PREFIX}/lib/cmake/gRPC")
set(grpc_DIR "${_IMPORT_PREFIX}/lib/cmake/gRPC")

# Clean up
set(_IMPORT_PREFIX)
""",
    "Protobuf": """# Generated by kvcache_cxx_packer
# Protobuf CMake Configuration File

# Compute the installation prefix relative to this file
get_filename_component(_IMPORT_PREFIX "${CMAKE_CURRENT_LIST_FILE}" PATH)
get_filename_component(_IMPORT_PREFIX "${_IMPORT_PREFIX}" PATH)
get_filename_component(_IMPORT_PREFIX "${_IMPORT_PREFIX}" PATH)
if(_IMPORT_PREFIX STREQUAL "/")
  set(_IMPORT_PREFIX "")
endif()

# Set the include directories
set(Protobuf_INCLUDE_DIRS "${_IMPORT_PREFIX}/include")
set(PROTOBUF_INCLUDE_DIRS "${_IMPORT_PREFIX}/include")
set(Protobuf_INCLUDE_DIR "${_IMPORT_PREFIX}/include")
set(PROTOBUF_INCLUDE_DIR "${_IMPORT_PREFIX}/include")

# Set the library directories
set(Protobuf_LIBRARY_DIRS "${_IMPORT_PREFIX}/lib")
set(PROTOBUF_LIBRARY_DIRS "${_IMPORT_PREFIX}/lib")

# Find the libraries using relative paths
find_library(Protobuf_LIBRARY NAMES protobuf PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(Protobuf_LITE_LIBRARY NAMES protobuf-lite PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)
find_library(Protoc_LIBRARY NAMES protoc PATHS "${_IMPORT_PREFIX}/lib" NO_DEFAULT_PATH)

# Find the protoc compiler
find_program(Protobuf_PROTOC_EXECUTABLE NAMES protoc PATHS "${_IMPORT_PREFIX}/bin" NO_DEFAULT_PATH)

# Set the found variables (both Protobuf_ and PROTOBUF_ prefixes for compatibility)
set(Protobuf_FOUND TRUE)
set(PROTOBUF_FOUND TRUE)
set(Protobuf_LIBRARIES ${Protobuf_LIBRARY})
set(PROTOBUF_LIBRARIES ${Protobuf_LIBRARY})

if(Protobuf_LITE_LIBRARY)
    list(APPEND Protobuf_LIBRARIES ${Protobuf_LITE_LIBRARY})
    list(APPEND PROTOBUF_LIBRARIES ${Protobuf_LITE_LIBRARY})
endif()

if(Protoc_LIBRARY)
    list(APPEND Protobuf_LIBRARIES ${Protoc_LIBRARY})
    list(APPEND PROTOBUF_LIBRARIES ${Protoc_LIBRARY})
endif()

# Set protoc executable
set(Protobuf_PROTOC_EXECUTABLE ${Protobuf_PROTOC_EXECUTABLE})
set(PROTOBUF_PROTOC_EXECUTABLE ${Protobuf_PROTOC_EXECUTABLE})

# Create imported targets
if(NOT TARGET protobuf::protobuf)
    add_library(protobuf::protobuf SHARED IMPORTED)
    set_target_properties(protobuf::protobuf PROPERTIES
        IMPORTED_LOCATION "${Protobuf_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${Protobuf_INCLUDE_DIRS}"
    )
endif()

if(Protobuf_LITE_LIBRARY AND NOT TARGET protobuf::protobuf-lite)
    add_library(protobuf::protobuf-lite SHARED IMPORTED)
    set_target_properties(protobuf::protobuf-lite PROPERTIES
        IMPORTED_LOCATION "${Protobuf_LITE_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${Protobuf_INCLUDE_DIRS}"
    )
endif()

if(Protoc_LIBRARY AND NOT TARGET protobuf::protoc)
    add_library(protobuf::protoc SHARED IMPORTED)
    set_target_properties(protobuf::protoc PROPERTIES
        IMPORTED_LOCATION "${Protoc_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${Protobuf_INCLUDE_DIRS}"
    )
endif()

# Create legacy targets for compatibility
if(NOT TARGET protobuf::libprotobuf)
    add_library(protobuf::libprotobuf ALIAS protobuf::protobuf)
endif()

if(Protobuf_LITE_LIBRARY AND NOT TARGET protobuf::libprotobuf-lite)
    add_library(protobuf::libprotobuf-lite ALIAS protobuf::protobuf-lite)
endif()

if(Protoc_LIBRARY AND NOT TARGET protobuf::libprotoc)
    add_library(protobuf::libprotoc ALIAS protobuf::protoc)
endif()

# Set directory variables for find_package compatibility
set(Protobuf_DIR "${_IMPORT_PREFIX}/lib/cmake/protobuf")
set(PROTOBUF_DIR "${_IMPORT_PREFIX}/lib/cmake/protobuf")
set(protobuf_DIR "${_IMPORT_PREFIX}/lib/cmake/protobuf")

# Clean up
set(_IMPORT_PREFIX)
""",
}
CPU_COUNT = min(4, os.cpu_count())

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("build.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class Builder:
    def __init__(
        self,
        install_prefix=OUTPUT_DIR,
        use_sudo=False,
        system_name=None,
    ):
        # 将install_prefix转换为绝对路径，确保所有安装都相对于pack.py所在目录
        if not os.path.isabs(install_prefix):
            # 获取pack.py脚本所在目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.install_prefix = os.path.join(script_dir, install_prefix)
        else:
            self.install_prefix = install_prefix

        # 确保目录存在
        os.makedirs(self.install_prefix, exist_ok=True)

        logger.info(f"Install prefix (absolute path): {self.install_prefix}")

        self.build_dir = Path(BUILD_DIR)
        self.build_dir.mkdir(exist_ok=True)
        self.output_logs_dir = Path(OUTPUT_LOGS_DIR)
        self.output_logs_dir.mkdir(exist_ok=True)
        self.build_results = {}
        self.built_packages = set()  # 跟踪已构建的包

        # 简化sudo处理：自动检测是否需要sudo
        if use_sudo:
            # 如果当前不是root用户，则使用sudo
            self.use_sudo = os.geteuid() != 0
            if self.use_sudo:
                logger.info(
                    "Running as non-root user, will use sudo for system operations"
                )
            else:
                logger.info("Running as root user, sudo not needed")
        else:
            self.use_sudo = False

        # 系统名称必须指定
        if not system_name:
            raise ValueError("system_name parameter is required")
        self.system_name = system_name
        logger.info(f"Using system name: {self.system_name}")

    def get_package_name(self, url: str) -> str:
        """从URL获取包名"""
        return url.split("/")[-1]

    def resolve_dependencies(self, packages: Dict) -> List[str]:
        """解析依赖关系，返回按依赖顺序排列的URL列表"""
        visited = set()
        temp_visited = set()
        result = []

        def visit(url: str):
            if url in temp_visited:
                raise ValueError(f"Circular dependency detected involving {url}")
            if url in visited:
                return

            temp_visited.add(url)

            # 处理依赖
            config = packages.get(url, {})
            dependencies = config.get("dependencies", [])

            for dep_name in dependencies:
                # 查找依赖的URL
                dep_url = None
                for pkg_url in packages:
                    if self.get_package_name(pkg_url) == dep_name:
                        dep_url = pkg_url
                        break

                if dep_url:
                    visit(dep_url)
                else:
                    logger.warning(
                        f"Dependency {dep_name} not found for {self.get_package_name(url)}"
                    )

            temp_visited.remove(url)
            visited.add(url)
            result.append(url)

        for url in packages:
            visit(url)

        return result

    def generate_cmake_args(self, config: Dict) -> str:
        """生成CMake配置参数"""
        args = []

        # 编译器设置
        if "CC" in os.environ:
            args.append(f"-DCMAKE_C_COMPILER={os.environ['CC']}")
        if "CXX" in os.environ:
            args.append(f"-DCMAKE_CXX_COMPILER={os.environ['CXX']}")

        # 基础参数
        build_type = config.get("build_type", "Release")
        args.append(f"-DCMAKE_BUILD_TYPE={build_type}")
        args.append(f"-DCMAKE_INSTALL_PREFIX={self.install_prefix}")

        # 统一设置基础编译标志（包含-fPIC）
        base_c_flags = "-fPIC"
        base_cxx_flags = "-fPIC"

        # 获取C++标准并添加到CXX标志中
        cpp_std = config.get("c++")
        if cpp_std:
            base_cxx_flags += f" -std=c++{cpp_std}"

        # 处理依赖包路径
        dependencies = config.get("dependencies", [])
        if dependencies:
            # 添加PREFIX_PATH以帮助查找已安装的依赖包
            # 只包含存在的路径，避免shell解析错误
            prefix_paths = [self.install_prefix]

            # 检查可能的cmake目录并添加存在的路径
            for subdir in ["lib64/cmake", "lib/cmake"]:
                cmake_path = f"{self.install_prefix}/{subdir}"
                if os.path.exists(cmake_path):
                    prefix_paths.append(cmake_path)

            args.append(f"-DCMAKE_PREFIX_PATH='{';'.join(prefix_paths)}'")

            # 在基础标志上添加包含路径和链接路径
            base_c_flags += f" -I{self.install_prefix}/include"
            base_cxx_flags += f" -I{self.install_prefix}/include"
            # 支持 lib 和 lib64
            linker_flags = f"-L{self.install_prefix}/lib -L{self.install_prefix}/lib64"

            args.append(f"-DCMAKE_EXE_LINKER_FLAGS='{linker_flags}'")
            args.append(f"-DCMAKE_SHARED_LINKER_FLAGS='{linker_flags}'")

            # 为每个依赖设置特定的路径变量
            for dep_name in dependencies:
                if dep_name in self.built_packages:
                    # 查找依赖包的配置以获取正确的 CMake 包名
                    cmake_name = dep_name  # 默认使用包名
                    for url, pkg_config in PACKS.items():
                        if self.get_package_name(url) == dep_name:
                            cmake_name = pkg_config.get(
                                "cmakename", dep_name
                            )  # 如果没有指定cmakename，使用包名
                            break

                    # 使用配置中的 CMake 包名设置变量
                    args.append(f"-D{cmake_name}_DIR={self.install_prefix}")
                    args.append(f"-D{cmake_name}_ROOT={self.install_prefix}")

                    # 如果cmake_name与包名不同，同时设置包名变体
                    if cmake_name != dep_name:
                        args.append(f"-D{dep_name}_DIR={self.install_prefix}")
                        args.append(f"-D{dep_name}_ROOT={self.install_prefix}")

                    # 添加大写版本（有些包需要）
                    args.append(f"-D{cmake_name.upper()}_ROOT={self.install_prefix}")

            # 添加pkg-config路径 - 支持多个可能的路径
            for subdir in ["lib/pkgconfig", "lib64/pkgconfig"]:
                pkgconfig_path = f"{self.install_prefix}/{subdir}"
                if os.path.exists(pkgconfig_path):
                    current_pkg_config = os.environ.get("PKG_CONFIG_PATH", "")
                    if pkgconfig_path not in current_pkg_config:
                        if current_pkg_config:
                            os.environ["PKG_CONFIG_PATH"] = (
                                f"{current_pkg_config}:{pkgconfig_path}"
                            )
                        else:
                            os.environ["PKG_CONFIG_PATH"] = pkgconfig_path
        else:
            # 没有依赖时，如果有C++标准要求，设置CMake标准变量
            if cpp_std:
                args.append(f"-DCMAKE_CXX_STANDARD={cpp_std}")
                args.append("-DCMAKE_CXX_STANDARD_REQUIRED=ON")

        # 统一设置编译标志（-fPIC已经包含在内）
        args.append(f"-DCMAKE_C_FLAGS='{base_c_flags}'")
        args.append(f"-DCMAKE_CXX_FLAGS='{base_cxx_flags}'")

        # 自定义定义
        defines = config.get("define", [])
        for define in defines:
            if isinstance(define, list) and len(define) == 2:
                key, value = define
                args.append(f"-D{key}={value}")
            elif isinstance(define, str):
                args.append(f"-D{define}")

        # 默认关闭测试
        if not any("BUILD_TESTING" in str(define) for define in defines):
            args.append("-DBUILD_TESTING=OFF")

        return " \\\n    ".join(args)

    def run_command(
        self, cmd: str, cwd: str = None, check: bool = True, need_sudo: bool = False
    ) -> int:
        """执行shell命令"""
        # 如果需要sudo且启用了use_sudo，添加sudo前缀
        if need_sudo and self.use_sudo:
            if not cmd.startswith("sudo "):
                cmd = f"sudo {cmd}"

        logger.info(f"Running command: {cmd}")
        if cwd:
            logger.info(f"Working directory: {cwd}")
            # 切换到指定目录执行命令
            original_cwd = os.getcwd()
            os.chdir(cwd)
            try:
                result = os.system(cmd)
            finally:
                os.chdir(original_cwd)
        else:
            result = os.system(cmd)

        if check and result != 0:
            raise subprocess.CalledProcessError(result, cmd)

        return result

    def get_system_packages_config(self):
        """根据系统名称获取包配置"""
        for syslib in SYSLIBS:
            if self.system_name in syslib["system"]:
                return syslib

        # 如果没有找到精确匹配，尝试部分匹配
        for syslib in SYSLIBS:
            for system in syslib["system"]:
                if system in self.system_name or self.system_name in system:
                    logger.info(f"Using partial match: {system} for {self.system_name}")
                    return syslib

        logger.warning(f"No package configuration found for system: {self.system_name}")
        return None

    def install_system_packages(self):
        """根据系统类型安装相应的依赖包"""
        logger.info(f"Installing system packages for {self.system_name}...")

        pkg_config = self.get_system_packages_config()
        if not pkg_config:
            logger.warning(
                f"Skipping package installation - no configuration for {self.system_name}"
            )
            return

        packages = pkg_config.get("packages", [])
        if not packages:
            logger.info(f"No packages defined for {self.system_name}")
            return

        package_manager = pkg_config.get("package_manager", "apt")

        # 根据包管理器类型设置命令
        if package_manager == "apt":
            update_command = "apt-get update"
            install_command = "apt-get install -y"
        elif package_manager == "yum":
            if self.system_name.startswith("manylinux"):
                # 对于 manylinux 系统，使用特殊的命令来跳过有问题的仓库
                update_command = (
                    "yum update -y --skip-broken --disablerepo=centos-sclo-sclo"
                )
                install_command = (
                    "yum install -y --skip-broken --disablerepo=centos-sclo-sclo"
                )
            else:
                update_command = "yum update -y"
                install_command = "yum install -y"
        elif package_manager == "apk":
            update_command = "apk update"
            install_command = "apk add"
        else:
            logger.warning(
                f"Unknown package manager: {package_manager}, using apt defaults"
            )
            update_command = "apt-get update"
            install_command = "apt-get install -y"

        logger.info(f"Using package manager: {package_manager}")
        logger.info(f"Installing {len(packages)} packages...")

        # 更新包列表
        logger.info("Updating package lists...")
        try:
            self.run_command(update_command, need_sudo=self.use_sudo)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Package list update failed: {e}")
            # 对于 manylinux，这可能是正常的，继续构建
            if not self.system_name.startswith("manylinux"):
                raise

        # 分批安装包，避免命令行过长
        batch_size = 20
        for i in range(0, len(packages), batch_size):
            batch = packages[i : i + batch_size]
            cmd = f"{install_command} {' '.join(batch)}"

            try:
                self.run_command(cmd, need_sudo=self.use_sudo)
                logger.info(
                    f"Successfully installed batch {i // batch_size + 1}: {batch}"
                )
            except subprocess.CalledProcessError as e:
                logger.warning(
                    f"Failed to install batch {i // batch_size + 1}: {batch}"
                )
                logger.warning(f"Error: {e}")
                # 尝试逐个安装失败的包
                for pkg in batch:
                    try:
                        single_cmd = f"{install_command} {pkg}"
                        self.run_command(single_cmd, need_sudo=self.use_sudo)
                        logger.info(f"Successfully installed individual package: {pkg}")
                    except subprocess.CalledProcessError:
                        logger.warning(f"Failed to install individual package: {pkg}")
                        # 对于 manylinux，某些包可能确实不可用，这是正常的
                        if self.system_name.startswith("manylinux"):
                            logger.info(
                                f"Skipping unavailable package {pkg} in manylinux environment"
                            )
                        else:
                            logger.error(
                                f"Package {pkg} installation failed in {self.system_name}"
                            )

        logger.info("System packages installation completed")

    def clone_repository(self, url: str, branch: str, target_dir: Path) -> bool:
        """克隆Git仓库"""
        try:
            if target_dir.exists():
                logger.info(
                    f"Directory {target_dir} already exists, pulling latest changes..."
                )
                self.run_command("git pull", cwd=str(target_dir))
                # 对于已存在的仓库，也更新子模块
                self.run_command(
                    "git submodule update --init --recursive",
                    cwd=str(target_dir),
                    check=False,
                )
            else:
                logger.info(f"Cloning {url} (branch: {branch}) to {target_dir}")
                # 对于某些需要子模块的包（如grpc），使用recursive克隆
                package_name = self.get_package_name(url)
                if package_name in ["grpc", "protobuf"]:
                    logger.info(f"Cloning {package_name} with submodules...")
                    self.run_command(
                        f"git clone --recursive -b {branch} {url} {target_dir}"
                    )
                else:
                    self.run_command(f"git clone -b {branch} {url} {target_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to clone {url}: {e}")
            return False

    def build_cmake_project(
        self, source_dir: Path, package_name: str, config: Dict
    ) -> bool:
        """构建CMake项目"""
        try:
            build_dir = source_dir / "build"
            build_dir.mkdir(exist_ok=True)

            # 生成CMake配置参数
            cmake_args = self.generate_cmake_args(config)
            cmake_cmd = f"cmake .. \\\n    {cmake_args}"

            self.run_command(cmake_cmd, cwd=str(build_dir))

            # 编译
            self.run_command(f"make -j{CPU_COUNT}", cwd=str(build_dir))

            # 安装 - 系统安装时可能需要sudo
            install_cmd = "make install"
            # 检查是否是系统目录安装，如果是则需要sudo
            need_sudo_for_install = self.use_sudo and (
                self.install_prefix.startswith("/usr/")
                or self.install_prefix.startswith("/opt/")
                or self.install_prefix == "/usr/local"
                or self.install_prefix.startswith("/usr/local/")
            )
            self.run_command(
                install_cmd, cwd=str(build_dir), need_sudo=need_sudo_for_install
            )

            # 标记为已构建
            self.built_packages.add(package_name)

            logger.info(f"Successfully built and installed {package_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to build {package_name}: {e}")
            return False

    def build_autotools_project(
        self, source_dir: Path, package_name: str, config: Dict
    ) -> bool:
        """构建Autotools项目"""
        try:
            # 尝试autogen.sh或autoreconf
            if (source_dir / "autogen.sh").exists():
                self.run_command("./autogen.sh", cwd=str(source_dir))
            elif (source_dir / "configure.ac").exists() or (
                source_dir / "configure.in"
            ).exists():
                self.run_command("autoreconf -fiv", cwd=str(source_dir))

            # 配置
            configure_cmd = f"./configure --prefix={self.install_prefix}"

            # 添加编译器设置
            if "CC" in os.environ:
                configure_cmd += f" CC={os.environ['CC']}"
            if "CXX" in os.environ:
                configure_cmd += f" CXX={os.environ['CXX']}"

            # 统一设置基础编译标志（包含-fPIC）
            base_cppflags = "-fPIC"
            base_cflags = "-fPIC"
            base_cxxflags = "-fPIC"
            base_ldflags = ""

            # 获取C++标准并添加到CXX标志中
            cpp_std = config.get("c++")
            if cpp_std:
                base_cxxflags += f" -std=c++{cpp_std}"

            # 处理依赖包路径
            dependencies = config.get("dependencies", [])
            if dependencies:
                # 在基础标志上添加包含路径和链接路径
                base_cppflags += f" -I{self.install_prefix}/include"
                base_cflags += f" -I{self.install_prefix}/include"
                base_cxxflags += f" -I{self.install_prefix}/include"
                base_ldflags += f" -L{self.install_prefix}/lib"

                # 设置PKG_CONFIG_PATH
                pkgconfig_path = f"{self.install_prefix}/lib/pkgconfig"
                if os.path.exists(pkgconfig_path):
                    current_pkg_config = os.environ.get("PKG_CONFIG_PATH", "")
                    if pkgconfig_path not in current_pkg_config:
                        if current_pkg_config:
                            os.environ["PKG_CONFIG_PATH"] = (
                                f"{current_pkg_config}:{pkgconfig_path}"
                            )
                        else:
                            os.environ["PKG_CONFIG_PATH"] = pkgconfig_path

            # 检查是否已有这些环境变量，如果有则合并
            existing_cppflags = os.environ.get("CPPFLAGS", "")
            existing_cflags = os.environ.get("CFLAGS", "")
            existing_cxxflags = os.environ.get("CXXFLAGS", "")
            existing_ldflags = os.environ.get("LDFLAGS", "")

            if existing_cppflags:
                base_cppflags = f"{existing_cppflags} {base_cppflags}"
            if existing_cflags:
                base_cflags = f"{existing_cflags} {base_cflags}"
            if existing_cxxflags:
                base_cxxflags = f"{existing_cxxflags} {base_cxxflags}"
            if existing_ldflags:
                base_ldflags = f"{existing_ldflags} {base_ldflags}"

            # 统一设置所有编译标志
            configure_cmd += f" CPPFLAGS='{base_cppflags}'"
            configure_cmd += f" CFLAGS='{base_cflags}'"
            configure_cmd += f" CXXFLAGS='{base_cxxflags}'"
            if base_ldflags.strip():
                configure_cmd += f" LDFLAGS='{base_ldflags}'"

            self.run_command(configure_cmd, cwd=str(source_dir))

            # 编译和安装
            self.run_command(f"make -j{CPU_COUNT}", cwd=str(source_dir))

            # 安装 - 系统安装时可能需要sudo
            install_cmd = "make install"
            # 检查是否是系统目录安装，如果是则需要sudo
            need_sudo_for_install = self.use_sudo and (
                self.install_prefix.startswith("/usr/")
                or self.install_prefix.startswith("/opt/")
                or self.install_prefix == "/usr/local"
                or self.install_prefix.startswith("/usr/local/")
            )
            self.run_command(
                install_cmd, cwd=str(source_dir), need_sudo=need_sudo_for_install
            )

            # 标记为已构建
            self.built_packages.add(package_name)

            logger.info(f"Successfully built and installed {package_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to build {package_name}: {e}")
            return False

    def build_package(self, url: str, config: Dict) -> tuple:
        """构建单个包"""
        package_name = self.get_package_name(url)
        source_dir = self.build_dir / package_name
        branch = config.get("branch", "master")

        logger.info(f"Building package: {package_name}")
        logger.info(f"Configuration: {config}")

        # 克隆仓库
        if not self.clone_repository(url, branch, source_dir):
            return (package_name, False, "Failed to clone repository")

        # 刷新ldconfig
        self.run_command("ldconfig", need_sudo=self.use_sudo)

        # 尝试不同的构建系统
        if (source_dir / "CMakeLists.txt").exists():
            success = self.build_cmake_project(source_dir, package_name, config)
        elif (source_dir / "configure").exists() or (
            source_dir / "autogen.sh"
        ).exists():
            success = self.build_autotools_project(source_dir, package_name, config)
        else:
            logger.warning(f"Unknown build system for {package_name}, trying CMake...")
            success = self.build_cmake_project(source_dir, package_name, config)

        if success:
            return (package_name, True, "Built successfully")
        else:
            return (package_name, False, "Build failed")

    def setup_compiler_environment(self):
        """设置编译器环境变量"""
        logger.info("Setting up compiler environment...")

        if self.system_name.startswith("manylinux"):
            # ManyLinux 系统使用 devtoolset-10
            logger.info("Setting up devtoolset-10 compiler environment...")

            # devtoolset-10 路径
            devtoolset_gcc = "/opt/rh/devtoolset-10/root/usr/bin/gcc"
            devtoolset_gxx = "/opt/rh/devtoolset-10/root/usr/bin/g++"

            if os.path.exists(devtoolset_gcc) and os.access(devtoolset_gcc, os.X_OK):
                os.environ["CC"] = devtoolset_gcc
                logger.info(f"Set CC={devtoolset_gcc}")
            else:
                logger.warning("devtoolset-10 gcc not found, using system default")

            if os.path.exists(devtoolset_gxx) and os.access(devtoolset_gxx, os.X_OK):
                os.environ["CXX"] = devtoolset_gxx
                logger.info(f"Set CXX={devtoolset_gxx}")
            else:
                logger.warning("devtoolset-10 g++ not found, using system default")

            # 设置 PATH 以包含 devtoolset-10
            devtoolset_bin = "/opt/rh/devtoolset-10/root/usr/bin"
            if os.path.exists(devtoolset_bin):
                current_path = os.environ.get("PATH", "")
                if devtoolset_bin not in current_path:
                    os.environ["PATH"] = f"{devtoolset_bin}:{current_path}"
                    logger.info(f"Added {devtoolset_bin} to PATH")

        else:
            # Ubuntu 等系统查找 gcc-10 和 g++-10
            logger.info("Setting up gcc-10/g++-10 compiler environment...")

            gcc_10_path = None
            gxx_10_path = None

            # 常见的安装路径
            common_paths = ["/usr/bin", "/usr/local/bin", "/opt/gcc/bin"]

            for path in common_paths:
                gcc_candidate = os.path.join(path, "gcc-10")
                gxx_candidate = os.path.join(path, "g++-10")

                if os.path.exists(gcc_candidate) and os.access(gcc_candidate, os.X_OK):
                    gcc_10_path = gcc_candidate
                if os.path.exists(gxx_candidate) and os.access(gxx_candidate, os.X_OK):
                    gxx_10_path = gxx_candidate

                if gcc_10_path and gxx_10_path:
                    break

            # 设置环境变量
            if gcc_10_path:
                os.environ["CC"] = gcc_10_path
                logger.info(f"Set CC={gcc_10_path}")
            else:
                logger.warning("gcc-10 not found, using system default")

            if gxx_10_path:
                os.environ["CXX"] = gxx_10_path
                logger.info(f"Set CXX={gxx_10_path}")
            else:
                logger.warning("g++-10 not found, using system default")

        # 验证编译器版本
        if "CC" in os.environ:
            logger.info("Verifying C compiler version:")
            os.system(f"{os.environ['CC']} --version")

        if "CXX" in os.environ:
            logger.info("Verifying C++ compiler version:")
            os.system(f"{os.environ['CXX']} --version")

    def setup_system_environment(self):
        """根据系统类型设置环境"""
        logger.info(f"Setting up system environment for: {self.system_name}")

        try:
            if self.system_name.startswith("ubuntu"):
                # Ubuntu 系统设置
                logger.info("Setting up Ubuntu environment...")

                # 设置时区，避免交互式提示
                self.run_command(
                    "ln -fs /usr/share/zoneinfo/UTC /etc/localtime",
                    need_sudo=self.use_sudo,
                    check=False,
                )

                # 更新包列表
                self.run_command("apt-get update", need_sudo=self.use_sudo)

                # 安装基础工具
                base_packages = [
                    "python3",
                    "python3-pip",
                    "sudo",
                    "wget",
                    "curl",
                    "git",
                    "build-essential",
                    "tzdata",
                ]

                cmd = f"DEBIAN_FRONTEND=noninteractive apt-get install -y {' '.join(base_packages)}"
                self.run_command(cmd, need_sudo=self.use_sudo)

            elif self.system_name.startswith("manylinux"):
                # ManyLinux 系统设置
                logger.info("Setting up ManyLinux environment...")

                # 启用 EPEL 仓库 (许多开发包在这里)
                logger.info("Enabling EPEL repository...")
                self.run_command(
                    "yum install -y epel-release", need_sudo=self.use_sudo, check=False
                )

                # 尝试安装 centos-release-scl，但不要因为失败而停止
                logger.info("Attempting to enable SCL repository...")
                self.run_command(
                    "yum install -y centos-release-scl",
                    need_sudo=self.use_sudo,
                    check=False,
                )

                # 更新包列表，但忽略失败的仓库
                logger.info("Updating package lists (skipping broken repositories)...")
                # 使用 --skip-broken 和禁用可能有问题的仓库
                update_cmd = (
                    "yum update -y --skip-broken --disablerepo=centos-sclo-sclo"
                )
                self.run_command(update_cmd, need_sudo=self.use_sudo, check=False)

                # 安装基础工具
                base_packages = [
                    "python3",
                    "python3-pip",
                    "sudo",
                    "wget",
                    "curl",
                    "git",
                ]

                cmd = f"yum install -y --skip-broken {' '.join(base_packages)}"
                self.run_command(cmd, need_sudo=self.use_sudo, check=False)

                # 安装开发工具
                self.run_command(
                    'yum groupinstall -y "Development Tools" --skip-broken',
                    need_sudo=self.use_sudo,
                    check=False,
                )

                # 尝试安装 devtoolset-10 (现代 GCC 版本)，但不要因为失败而停止
                logger.info("Attempting to install devtoolset-10...")
                devtoolset_cmd = "yum install -y devtoolset-10-gcc devtoolset-10-gcc-c++ devtoolset-10-binutils --skip-broken --disablerepo=centos-sclo-sclo"
                self.run_command(devtoolset_cmd, need_sudo=self.use_sudo, check=False)

                # 启用 devtoolset-10
                scl_enable_script = "/opt/rh/devtoolset-10/enable"
                if os.path.exists(scl_enable_script):
                    logger.info("Found devtoolset-10, enabling it...")
                    # 执行 scl enable 脚本来设置环境变量
                    self.run_command(f"source {scl_enable_script}", check=False)

                    # 手动设置编译器环境变量
                    os.environ["CC"] = "/opt/rh/devtoolset-10/root/usr/bin/gcc"
                    os.environ["CXX"] = "/opt/rh/devtoolset-10/root/usr/bin/g++"
                    os.environ["PATH"] = (
                        f"/opt/rh/devtoolset-10/root/usr/bin:{os.environ.get('PATH', '')}"
                    )

                    logger.info(f"Set CC={os.environ['CC']}")
                    logger.info(f"Set CXX={os.environ['CXX']}")
                else:
                    logger.info("devtoolset-10 not available, will use system compiler")

                # 安装 cmake3 并创建 cmake 符号链接
                self.run_command(
                    "yum install -y cmake3 --skip-broken",
                    need_sudo=self.use_sudo,
                    check=False,
                )
                # 创建 cmake 符号链接
                self.run_command(
                    "ln -sf /usr/bin/cmake3 /usr/bin/cmake",
                    need_sudo=self.use_sudo,
                    check=False,
                )

                # 检查python3是否存在，如果不存在则创建链接
                result = self.run_command("command -v python3", check=False)
                if result != 0:
                    logger.info("Creating python3 symlink...")
                    self.run_command(
                        "ln -s /usr/bin/python /usr/bin/python3",
                        need_sudo=self.use_sudo,
                        check=False,
                    )

            else:
                # 其他系统的通用设置
                logger.info("Setting up generic Linux environment...")

                # 尝试检测包管理器并安装基础工具
                if self.run_command("command -v apt-get", check=False) == 0:
                    # Debian/Ubuntu 系列
                    self.run_command("apt-get update", need_sudo=self.use_sudo)
                    cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y python3 git build-essential"
                    self.run_command(cmd, need_sudo=self.use_sudo)
                elif self.run_command("command -v yum", check=False) == 0:
                    # RedHat/CentOS 系列
                    self.run_command("yum update -y", need_sudo=self.use_sudo)
                    self.run_command(
                        "yum install -y python3 git", need_sudo=self.use_sudo
                    )
                    self.run_command(
                        'yum groupinstall -y "Development Tools"',
                        need_sudo=self.use_sudo,
                    )
                else:
                    logger.warning("Unknown package manager, skipping system setup")

            # 验证Python安装
            logger.info("Verifying Python installation...")
            python_result = self.run_command("python3 --version", check=False)
            if python_result != 0:
                # 尝试使用python
                fallback_result = self.run_command("python --version", check=False)
                if fallback_result != 0:
                    logger.warning("Neither python3 nor python found")
                else:
                    logger.info("Using python instead of python3")

            logger.info("System environment setup completed")

        except Exception as e:
            logger.error(f"Failed to setup system environment: {e}")
            # 不要因为环境设置失败而停止整个构建过程
            logger.warning("Continuing with build despite environment setup issues...")

    def _copy_library_file(
        self, src_file, target_name, output_lib_dir, is_rename=False, original_name=None
    ):
        """
        复制单个库文件的统一函数

        Args:
            src_file: 源文件路径
            target_name: 目标文件名
            output_lib_dir: 输出目录
            is_rename: 是否为重命名操作
            original_name: 原始文件名（用于重命名日志）

        Returns:
            tuple: (success: bool, copied_file_path: str or None)
        """
        try:
            src_path = Path(src_file)
            dst_path = output_lib_dir / target_name

            # 如果是符号链接，复制链接指向的实际文件
            if src_path.is_symlink():
                real_src = src_path.resolve()
                if real_src.exists():
                    shutil.copy2(real_src, dst_path)
                    if is_rename:
                        logger.info(
                            f"Copied and renamed symlink target: {real_src} -> {dst_path} (renamed from {original_name})"
                        )
                    else:
                        logger.info(f"Copied symlink target: {real_src} -> {dst_path}")
                    return True, str(dst_path)
            else:
                shutil.copy2(src_file, dst_path)
                if is_rename:
                    logger.info(
                        f"Copied and renamed: {src_file} -> {dst_path} (renamed from {original_name})"
                    )
                else:
                    logger.info(f"Copied: {src_file} -> {dst_path}")
                return True, str(dst_path)

        except Exception as e:
            logger.warning(f"Failed to copy {src_file}: {e}")
            return False, None

    def copy_dynamic_libraries(self):
        """复制系统动态库文件到输出目录"""
        logger.info("Copying dynamic libraries to output directory...")

        # 创建输出lib目录
        output_lib_dir = Path(self.install_prefix) / "lib"
        output_lib_dir.mkdir(parents=True, exist_ok=True)

        # 系统库目录列表
        system_lib_dirs = [
            "/usr/lib",
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib64",
            "/usr/local/lib",
            "/usr/local/lib64",
            "/lib",
            "/lib/x86_64-linux-gnu",
            "/lib64",
        ]

        copied_files = []
        failed_patterns = []

        # 第一阶段：处理 DYNAMIC_COPY 模式匹配拷贝
        logger.info("Stage 1: Copying files by pattern matching...")
        for pattern in DYNAMIC_COPY:
            found_files = []

            # 在每个系统目录中搜索匹配的文件
            for lib_dir in system_lib_dirs:
                if os.path.exists(lib_dir):
                    search_pattern = os.path.join(lib_dir, pattern)
                    matches = glob.glob(search_pattern)
                    found_files.extend(matches)

            if found_files:
                logger.info(
                    f"Found {len(found_files)} files matching pattern '{pattern}'"
                )

                for src_file in found_files:
                    src_path = Path(src_file)
                    target_name = src_path.name  # 不重命名，使用原文件名

                    success, copied_path = self._copy_library_file(
                        src_file, target_name, output_lib_dir, is_rename=False
                    )

                    if success and copied_path:
                        copied_files.append(copied_path)
            else:
                logger.warning(f"No files found matching pattern '{pattern}'")
                failed_patterns.append(pattern)

        # 第二阶段：处理 DYNAMIC_COPY_RENAME 精确查找和重命名
        logger.info("Stage 2: Copying and renaming specific files...")
        failed_renames = []

        for original_name, target_name in DYNAMIC_COPY_RENAME:
            found_src = None

            # 在系统目录中查找原始文件名
            for lib_dir in system_lib_dirs:
                if os.path.exists(lib_dir):
                    candidate_path = os.path.join(lib_dir, original_name)
                    if os.path.exists(candidate_path):
                        found_src = candidate_path
                        break

            if found_src:
                success, copied_path = self._copy_library_file(
                    found_src,
                    target_name,
                    output_lib_dir,
                    is_rename=True,
                    original_name=original_name,
                )

                if success and copied_path:
                    copied_files.append(copied_path)
                else:
                    failed_renames.append(original_name)
            else:
                logger.warning(f"File not found for renaming: {original_name}")
                failed_renames.append(original_name)

        # 更新动态链接器缓存
        if copied_files:
            logger.info(
                f"Successfully copied {len(copied_files)} dynamic library files"
            )
            # 添加输出lib目录到LD_LIBRARY_PATH
            current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
            new_ld_path = str(output_lib_dir)
            if current_ld_path:
                os.environ["LD_LIBRARY_PATH"] = f"{new_ld_path}:{current_ld_path}"
            else:
                os.environ["LD_LIBRARY_PATH"] = new_ld_path

            # 更新ldconfig缓存
            try:
                self.run_command("ldconfig", need_sudo=self.use_sudo)
            except:
                logger.warning("Failed to update ldconfig cache")

        # 报告失败的情况
        if failed_patterns:
            logger.warning(f"Failed to find files for patterns: {failed_patterns}")
        if failed_renames:
            logger.warning(f"Failed to find/rename files: {failed_renames}")

        return copied_files

    def generate_cmake_config_files(self):
        """为指定的库生成CMake配置文件"""
        logger.info("Generating CMake config files...")

        cmake_dir = Path(self.install_prefix) / "lib" / "cmake"
        cmake_dir.mkdir(parents=True, exist_ok=True)

        generated_configs = []

        for lib_name, config_content in CREATE_LIB_CMAKE_CONFIG.items():
            if config_content.strip():  # 只处理非空配置
                # 为每个库创建子目录
                lib_cmake_dir = cmake_dir / lib_name
                lib_cmake_dir.mkdir(parents=True, exist_ok=True)

                # 生成 Find<LibName>.cmake 文件
                find_config_file = lib_cmake_dir / f"Find{lib_name}.cmake"
                with open(find_config_file, "w") as f:
                    f.write(config_content)

                # 生成 <lib_name>-config.cmake 文件 (标准命名)
                config_file = lib_cmake_dir / f"{lib_name}-config.cmake"
                with open(config_file, "w") as f:
                    f.write(config_content)

                # 生成版本文件 (可选，这里设置一个通用版本)
                version_file = lib_cmake_dir / f"{lib_name}-config-version.cmake"
                version_content = f"""# Generated by kvcache_cxx_packer
# Version file for {lib_name}

set(PACKAGE_VERSION "1.0.0")

# Check whether the requested PACKAGE_FIND_VERSION is compatible
if("${{PACKAGE_VERSION}}" VERSION_LESS "${{PACKAGE_FIND_VERSION}}")
  set(PACKAGE_VERSION_COMPATIBLE FALSE)
else()
  set(PACKAGE_VERSION_COMPATIBLE TRUE)
  if ("${{PACKAGE_VERSION}}" VERSION_EQUAL "${{PACKAGE_FIND_VERSION}}")
    set(PACKAGE_VERSION_EXACT TRUE)
  endif()
endif()
"""
                with open(version_file, "w") as f:
                    f.write(version_content)

                generated_configs.extend([find_config_file, config_file, version_file])
                logger.info(f"Generated CMake config for {lib_name} in {lib_cmake_dir}")

        # 更新CMake模块路径环境变量
        cmake_module_path = str(cmake_dir)
        current_cmake_path = os.environ.get("CMAKE_MODULE_PATH", "")
        if cmake_module_path not in current_cmake_path:
            if current_cmake_path:
                os.environ["CMAKE_MODULE_PATH"] = (
                    f"{current_cmake_path}:{cmake_module_path}"
                )
            else:
                os.environ["CMAKE_MODULE_PATH"] = cmake_module_path

        logger.info(f"Generated {len(generated_configs)} CMake config files")
        return generated_configs

    def clean_cmake_config_files(self):
        """清理之前生成的CMake配置文件，避免在构建时产生冲突"""
        logger.info("Cleaning up previously generated CMake config files...")

        cmake_dir = Path(self.install_prefix) / "lib" / "cmake"
        if not cmake_dir.exists():
            logger.info("No CMake config directory found, skipping cleanup")
            return

        cleaned_files = []

        for lib_name in CREATE_LIB_CMAKE_CONFIG.keys():
            lib_cmake_dir = cmake_dir / lib_name
            if lib_cmake_dir.exists():
                try:
                    # 删除整个库的CMake配置目录
                    shutil.rmtree(lib_cmake_dir)
                    cleaned_files.append(str(lib_cmake_dir))
                    logger.info(
                        f"Cleaned CMake config directory for {lib_name}: {lib_cmake_dir}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to clean CMake config directory for {lib_name}: {e}"
                    )

        # 如果CMAKE_MODULE_PATH环境变量包含了cmake目录，暂时移除它
        current_cmake_path = os.environ.get("CMAKE_MODULE_PATH", "")
        cmake_module_path = str(cmake_dir)
        if cmake_module_path in current_cmake_path:
            # 从环境变量中移除cmake目录路径
            path_parts = current_cmake_path.split(":")
            path_parts = [p for p in path_parts if p != cmake_module_path]
            if path_parts:
                os.environ["CMAKE_MODULE_PATH"] = ":".join(path_parts)
            else:
                os.environ.pop("CMAKE_MODULE_PATH", None)
            logger.info(
                f"Temporarily removed {cmake_module_path} from CMAKE_MODULE_PATH"
            )

        if cleaned_files:
            logger.info(f"Cleaned {len(cleaned_files)} CMake config directories")
        else:
            logger.info("No CMake config files to clean")

        return cleaned_files

    def build_all_packages(self):
        """按依赖顺序构建所有包"""
        logger.info("Starting to build all packages...")

        # 首先设置系统环境
        self.setup_system_environment()

        # 然后安装系统包
        self.install_system_packages()

        # 设置编译器环境
        self.setup_compiler_environment()

        # 清理之前生成的CMake配置文件，避免在构建时产生冲突
        self.clean_cmake_config_files()

        # 解析依赖顺序
        try:
            build_order = self.resolve_dependencies(PACKS)
            logger.info(
                f"Build order: {[self.get_package_name(url) for url in build_order]}"
            )
        except ValueError as e:
            logger.error(f"Dependency resolution failed: {e}")
            return {}

        # 按顺序构建包（不能并行，因为有依赖关系）
        for url in build_order:
            config = PACKS[url]
            package_name, success, message = self.build_package(url, config)

            self.build_results[package_name] = {
                "url": url,
                "success": success,
                "message": message,
            }

            if not success:
                logger.error(f"Failed to build {package_name}, stopping build process")
                break

        # 复制系统动态库文件到输出目录
        try:
            copied_files = self.copy_dynamic_libraries()
            logger.info(
                f"Dynamic library copy completed, {len(copied_files)} files copied"
            )
        except Exception as e:
            logger.error(f"Failed to copy dynamic libraries: {e}")

        # 生成CMake配置文件
        try:
            generated_configs = self.generate_cmake_config_files()
            logger.info(
                f"CMake config generation completed, {len(generated_configs)} files generated"
            )
        except Exception as e:
            logger.error(f"Failed to generate CMake config files: {e}")

        # 最后更新动态链接器缓存
        self.run_command("ldconfig", need_sudo=self.use_sudo)

        return self.build_results

    def generate_report(self, output_dir: Path):
        """生成构建报告"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 生成JSON报告
        report_file = output_dir / "build_report.json"
        with open(report_file, "w") as f:
            json.dump(self.build_results, f, indent=2)

        # 生成文本报告
        text_report = output_dir / "build_report.txt"
        with open(text_report, "w") as f:
            f.write("Build Report\n")
            f.write("=" * 50 + "\n\n")

            successful = 0
            failed = 0

            for package, result in self.build_results.items():
                status = "SUCCESS" if result["success"] else "FAILED"
                f.write(f"{package}: {status}\n")
                f.write(f"  URL: {result['url']}\n")
                f.write(f"  Message: {result['message']}\n\n")

                if result["success"]:
                    successful += 1
                else:
                    failed += 1

            f.write(f"Summary: {successful} successful, {failed} failed\n")

        # 复制日志文件
        if os.path.exists("build.log"):
            shutil.copy("build.log", output_dir / "build.log")

        logger.info(f"Build report generated in {output_dir}")

    def clean(self):
        # Clean previous old artifacts.
        try:
            # 对于非output目录，要小心删除
            if self.install_prefix != OUTPUT_DIR and (
                self.install_prefix.startswith("/usr/")
                or self.install_prefix.startswith("/opt/")
                or self.install_prefix == "/usr/local"
                or self.install_prefix.startswith("/usr/local/")
            ):
                logger.warning(
                    f"System directory cleanup skipped for safety: {self.install_prefix}"
                )
                logger.warning("Please manually remove installed files if needed")
            else:
                shutil.rmtree(self.install_prefix, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Failed to clean install prefix {self.install_prefix}: {e}")

        # 这些目录通常是安全的清理目标
        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.output_logs_dir, ignore_errors=True)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Build all packages defined in pack.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  local     Install packages to local directory (./output)
  system    Install packages to system directory (/usr/local)

Examples:
  python3 pack.py local --system-name ubuntu20.04
  python3 pack.py system --system-name ubuntu22.04
  
  # Or use environment variable (for CI):
  SYSTEM_NAME=ubuntu20.04 python3 pack.py local
        """,
    )

    # 添加子命令
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # local 子命令：安装到本地目录
    local_parser = subparsers.add_parser(
        "local", help="Install packages to local directory"
    )
    local_parser.add_argument(
        "--system-name",
        required=True,
        help="System name (e.g., ubuntu20.04, manylinux_2014)",
    )

    # system 子命令：安装到系统目录
    system_parser = subparsers.add_parser(
        "system", help="Install packages to system directory (/usr/local)"
    )
    system_parser.add_argument(
        "--system-name",
        required=True,
        help="System name (e.g., ubuntu20.04, manylinux_2014)",
    )

    # 为了向后兼容，如果没有指定子命令，添加原有的参数选项
    parser.add_argument(
        "--system-name", help="System name (e.g., ubuntu20.04, manylinux_2014)"
    )

    args = parser.parse_args()

    # 获取系统名称：优先从命令行参数，否则从环境变量
    system_name = getattr(args, "system_name", None) or os.environ.get("SYSTEM_NAME")
    if not system_name:
        logger.error(
            "System name is required. Specify it via --system-name argument or SYSTEM_NAME environment variable"
        )
        logger.error(
            "Available options: ubuntu20.04, ubuntu22.04, manylinux_2014, manylinux_2_24"
        )
        sys.exit(1)

    logger.info(f"Using system name: {system_name}")

    # 处理命令和参数
    if args.command == "system":
        install_prefix = SYSTEM_INSTALL_PREFIX
        use_sudo = True  # 系统安装总是需要sudo检查
        is_system_install = True

    elif args.command == "local":
        install_prefix = OUTPUT_DIR
        use_sudo = False
        is_system_install = False

    else:
        # 向后兼容：没有指定子命令时使用原有行为（默认本地安装）
        install_prefix = OUTPUT_DIR
        use_sudo = False
        is_system_install = False

    try:
        # Fix broken installs (only for system install)
        if is_system_install:
            os.system(
                "apt --fix-broken install 2>/dev/null || yum check 2>/dev/null || true"
            )

        builder = Builder(
            install_prefix=install_prefix,
            use_sudo=use_sudo,
            system_name=system_name,
        )

        # clean before build.
        builder.clean()

        results = builder.build_all_packages()
        builder.generate_report(Path(OUTPUT_LOGS_DIR))

        # 打印摘要
        successful = sum(1 for r in results.values() if r["success"])
        total = len(results)

        logger.info(
            f"Build completed: {successful}/{total} packages built successfully"
        )

        # 获取架构信息
        arch = platform.machine()

        # 输出系统信息
        logger.info(f"System: {builder.system_name}")
        logger.info(f"Architecture: {arch}")

        if not is_system_install:
            logger.info(f"Packages built and installed to: {install_prefix}")
        else:
            logger.info(f"Packages installed to system directory: {install_prefix}")
            logger.info("Run 'sudo ldconfig' to update library cache if needed")

        if successful == total:
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Build failed with exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
