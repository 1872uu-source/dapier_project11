from setuptools import setup, find_packages

package_name = "nomi_agent"

setup(
    name=package_name,
    version="0.0.1",
    packages=find_packages(exclude=("tests", "tests.*")),
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        (
            "share/" + package_name,
            ["package.xml"],
        ),
    ],
    install_requires=[
        "setuptools",
        "requests",
        "openai>=1.0.0",
        "ollama>=0.3.0",
        "python-dotenv>=1.0.0",
    ],
    zip_safe=True,
    maintainer="user",
    maintainer_email="user@example.com",
    description="NOMI LLM-based robot command agent",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "agent = nomi_agent.agent_node:main",
        ],
    },
)
