from setuptools import setup, find_packages

setup(
    name="fi_risk_dashboard",
    version="0.1.0",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "streamlit>=1.32.0",
        "plotly>=5.20.0",
        "requests>=2.31.0",
        "python-dotenv>=1.0.0",
        "mcp>=1.0.0",
        "scipy>=1.13.0",
        "numpy>=2.0.0",
        "pandas>=2.0.0",
    ],
)
