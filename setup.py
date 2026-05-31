from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


setup(
    name="codex-recap-agent",
    version="0.1.0",
    description="Local daily recap generator for Codex sessions",
    long_description=README,
    long_description_content_type="text/markdown",
    author="yzongy",
    author_email="billyangzy@gmail.com",
    license="MIT",
    python_requires=">=3.9",
    packages=find_packages("src"),
    package_dir={"": "src"},
    include_package_data=True,
    url="https://github.com/yzongy/codex-recap-agent",
    project_urls={
        "Homepage": "https://github.com/yzongy/codex-recap-agent",
        "Repository": "https://github.com/yzongy/codex-recap-agent",
        "Issues": "https://github.com/yzongy/codex-recap-agent/issues",
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Topic :: Software Development :: Documentation",
        "Topic :: Utilities",
    ],
    entry_points={"console_scripts": ["codex-recap=codex_recap_agent.cli:main"]},
)
