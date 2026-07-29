from setuptools import find_packages, setup

package_name = "fta_tools"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/registry_example.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="soobin Jeon",
    maintainer_email="marsberry@cu.ac.kr",
    description="FTA 검증용 도구 — 테스트 리시버 (FR-8)",
    license="MIT",
    entry_points={
        "console_scripts": [
            "test_receiver = fta_tools.test_receiver:main",
            "registry_tool = fta_tools.registry_tool:main",
        ],
    },
)
