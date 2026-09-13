#!/bin/bash
# Setup script for Buy or Wait? solution

echo "Setting up Buy or Wait? solution..."

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r code/requirements.txt

echo ""
echo "Setup complete!"
echo ""
echo "To run the solution:"
echo "1. Activate the virtual environment: source venv/bin/activate"
echo "2. Set your API key: export ANTHROPIC_API_KEY='your-api-key-here'"
echo "3. Run the solution: python3 code/main.py"
echo ""
echo "To deactivate: deactivate"
