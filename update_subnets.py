name: Update Bittensor Subnets (Blockchain)

on:
  schedule:
    # Run every 12 hours (0:00, 12:00 UTC)
    - cron: '0 0,12 * * *'
  
  # Allow manual trigger from GitHub UI
  workflow_dispatch:

jobs:
  update-subnets:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests bittensor
      
      - name: Run Bittensor blockchain subnet populator
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
        run: python update_subnets.py
        continue-on-error: false
