# OnboardIQ

OnboardIQ is an agentic data onboarding and migration workspace built with a NiceGUI frontend and a Python backend. It can profile source data, generate migration artifacts, and run an interactive assistant for reviewing the pipeline outputs.

## Prerequisites

- Python 3.11 or newer
- `pip`
- Access to either:
  - AWS Bedrock credentials, or
  - a `GROQ_API_KEY`

## Setup

1. Open a terminal in the `OnboardIQ` directory.
2. Create and activate a virtual environment.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

3. Install the dependencies.

```powershell
pip install -r requirements.txt
```

4. Configure environment variables in `.env`.

The app loads variables from `OnboardIQ/.env` at startup. At minimum, provide one working LLM provider:

- AWS Bedrock:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION` or `AWS_DEFAULT_REGION`
  - `AWS_BEDROCK_MODEL`
- Groq:
  - `GROQ_API_KEY`
  - optional `GROQ_MODEL`

Optional settings:

- `USE_S3_SOURCE=true` to read uploads from S3 instead of the local workspace
- `S3_BUCKET` and `S3_INPUT_PREFIX` when using S3
- `FRONTEND_PORT` if you want the web app on a different port
- `OBQ_LOG_LEVEL` and `OBQ_QUIET_TERMINAL` for local logging behavior

## Run the app

Start the NiceGUI web app:

```powershell
python frontend\main.py
```

By default, the app tries port `8081` and automatically moves to the next free port if needed.

## Run the pipeline from the CLI

You can also run the backend pipeline directly against a folder of supported input files:

```powershell
python backend\main.py run --input data\sample
```

The pipeline accepts `.csv`, `.json`, and `.sql` files.

To launch the conversational assistant after the pipeline finishes:

```powershell
python backend\main.py run --input data\sample --chat
```

## Project Structure

- `frontend/` - NiceGUI app, pages, middleware, and layout
- `backend/` - pipeline orchestration, agents, adapters, and storage logic
- `data/` - local input data and sample files
- `outputs/` - generated reports and artifacts
- `schemas/` - target schema definitions
- `workspaces/` - per-user workspace data when running the app

## Notes

- The frontend and pipeline both validate environment variables on startup.
- If startup fails with an authentication error, verify that your AWS or Groq credentials are present and valid.
- If you use a custom input folder, make sure it contains at least one supported file type.

## Troubleshooting

- `No supported files found`: add at least one `.csv`, `.json`, or `.sql` file to the input directory.
- `AWS or Groq credentials missing`: set either Bedrock credentials, an AWS bearer token, or `GROQ_API_KEY`.
- `Port already in use`: set `FRONTEND_PORT` to a different value and restart the app.
