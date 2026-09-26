from setuptools import find_packages, setup

setup(
    name="espacenet-cli",
    version="0.5.0",
    description="Agent-first command-line client for Espacenet (worldwide.espacenet.com) — patent search, biblio, claims, family, legal, PDF with built-in fair-use rate limiting",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(include=["espacenet_cli", "espacenet_cli.*"]),
    install_requires=[
        "click>=8.0.0",
        "prompt-toolkit>=3.0.0",
        "playwright>=1.40.0",
    ],
    entry_points={
        "console_scripts": [
            "espacenet=espacenet_cli.cli:main",
        ],
    },
    package_data={
        "espacenet_cli": ["skills/*.md"],
    },
    python_requires=">=3.10",
)
