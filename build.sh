#!/bin/bash
#--------------------------------------------------------------
#  Just a local example.
#  Build and PyPi upload is done via CI on Release Publishing.
#--------------------------------------------------------------
set -e

echo "🧹 Cleaning up old build artifacts..."
rm -rf build/ dist/ *.egg-info src/*.egg-info

if [ ! -d "venv" ]; then
    echo "Creating a fresh virtual environment (venv)..."
    python3 -m venv venv
fi

echo " Activating sandbox virtual environment..."
source venv/bin/activate

echo "Ensuring core build tools are present..."
pip install --upgrade pip
pip install build twine

echo "Compiling package distributions..."
python3 -m build

echo "Success! Clean wheel and sdist generated in 'dist/'"
