# NestLab

Retirement planner and monthly budget calculator. An AI Upscale LLC tool.

Save named plans in the sidebar, download them as JSON, and upload them again on any machine. When the server can write files, plans also persist in `data/plans.json`.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run nestlab.py
```

## Deploy (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io), create an app from the repo.
3. Set **Main file path** to `nestlab.py`.
4. Leave Python to the `runtime.txt` version (3.12).

Streamlit Cloud wipes the local disk on reboot, so treat **Download plans JSON** as the durable save. Upload that file to restore everything.

## What it models

- Nest egg growth with contributions, employer money, and separate pre / post-retirement returns
- Inflation on spending, Social Security, pension, and other income
- A 4% rule target plus a year-by-year “does the money last?” check
- The extra monthly savings the model says you need if the plan falls short
- A 50/30/20 budget split, housing ratio, and a surplus that can feed the retirement tab

Planning estimates only — not financial, tax, or investment advice.
