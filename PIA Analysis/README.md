# PIA Analysis (`piaa`) - v0.3.24

Local web app that reviews World Bank project documents and extracts digital & AI innovation approaches.
Runs on your computer in a private Python environment and opens in your browser.

## Quick start (Windows)
1. Unzip anywhere.
2. Double-click **setup.bat** (builds a private `.venv`, installs everything).
3. Double-click **start.bat** -> opens <http://127.0.0.1:18765>.
4. In the app's **Setup** page set your Anthropic API key, raw_data folder and output folder.

`raw_data` holds your `projects.csv` and `documents\`. Missing project documents are fetched automatically from the public World Bank Documents API into `output\supplement_documents\` during a run.

Full guide with troubleshooting: open **README.html** (double-click).
