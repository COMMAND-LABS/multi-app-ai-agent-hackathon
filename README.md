# Multi-App AI Agent Hackathon

Hosted by Lemma.ai and Comma Capital. Judged by Arga Labs and Userlens. This is Tad Duval's (tad@cmdlabs.io) submission.

## Project Overview

Claude Code acts as an agent that automates Social Media Marketing end-2-end with a final human review step.

- STEP 1: Pipeline is configure via a list of YouTube channels to source topics from
  - Channels are analyzed for “outlier multiple” and “repeatability”
- STEP 2: ElevenLabs + HyperFrames SUBAGENT
  - Used to generate voice and music when producing a video based on the generated
- STEP 3: Google Cloud Storage
  - Used to store the generated video file for later upload to the Metricool API
- STEP 4: Metricool
  - Final step is to schedule the content for distribution to Social Media

## External Apps Used

- YouTube
- Airtable
- Google Cloud Storage
- Metricool
- PLUS a HyperFrames video sub-agent.

Each integration is a small Python client plus a CLI, a Claude skill under `.claude/skills/`, and pulled data lands in `data/`.

## Setup instructions

- Have Claude Code installed (https://code.claude.com/docs/en/quickstart)
- Clone the project
- Provide all the environment variable outlined in the `.env.example` file
- Configure the application via the `pipeline.toml` file
- Open 2 terminal windows...
  - Run this in the 1st one: `uv run python -m analysis.progress -f`
  - Run this in the 2nd one: `uv run python -m analysis.pipeline`
- ALSO: Refer to the `READMEs` directory for detailed setup steps for integrating with each 3rd-party app

## Reliability testing

- `uv run python -m analysis.evaluate` checks every artifact of a run against what the pipeline promised and writes `reports/<run_id>/evaluation.md` with a PASS/WARN/FAIL table. It exits non-zero on any FAIL, so it works as a gate in the orchestrator.
- `uv run pytest` runs the offline unit tests (outlier math, topic similarity, brief scrubbing, Airtable and Metricool payload shapes, secret redaction in the logs).
- Every external write has a `--dry-run` that produces the same receipt without touching the service.
- Re-running any step is safe: Airtable upserts, GCS overwrites the same object, Metricool records the post id so you can see duplicates before they happen.

## Demo video

https://youtu.be/D6rgPAVBh3w

## License

MIT. See [LICENSE](LICENSE).
