from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="livekit-mcp-client",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Universal MCP client adaptor for LiveKit Agents with intelligent voice announcements",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/livekit-mcp-client",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "livekit-agents>=1.2.0",
        "livekit-plugins-openai>=0.6.0",
        "mcp>=1.0.0",
        "openai>=1.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
        ],
    },
    keywords="livekit mcp agents voice assistant announcements",
)
