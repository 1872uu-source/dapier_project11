from glob import glob
from setuptools import setup

package_name = "nomi_xlerobot_sim"

setup(
    name=package_name,
    version="0.0.1",
    packages=[package_name],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            [f"resource/{package_name}"],
        ),
        (
            f"share/{package_name}",
            ["package.xml"],
        ),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/rviz", glob("rviz/*.rviz")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "mujoco_host = nomi_xlerobot_sim.mujoco_host:main",
        ],
    },
)
