#!/bin/bash
# Quick run script for Buy or Wait? solution

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Running setup..."
    ./setup.sh
fi

# Activate virtual environment
source venv/bin/activate

# Check if API key is set
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  Warning: ANTHROPIC_API_KEY not set!"
    echo "Please set it with: export ANTHROPIC_API_KEY='your-api-key-here'"
    exit 1
fi

# Run the solution
echo "Running Buy or Wait? solution..."
python3 code/main.py

# Deactivate virtual environment
deactivate

echo ""
echo "✅ Done! Check output.csv for results."
