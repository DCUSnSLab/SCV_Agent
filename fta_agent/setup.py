from setuptools import find_packages, setup

package_name = "fta_agent"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (
            "share/" + package_name + "/config",
            ["config/fta_example.yaml", "config/fta_m2_example.yaml"],
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="soobin Jeon",
    maintainer_email="marsberry@cu.ac.kr",
    description="FTA (Fleet Telemetry Agent) — ROS2 텔레메트리 차량측 에이전트",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "agent = fta_agent.agent_node:main",
        ],
    },
)
