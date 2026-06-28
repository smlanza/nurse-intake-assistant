# Demo Page Smoke Test

Use this checklist to manually verify the local demo page in safe mock mode.

## Start the App

From the project root:

```bash
uvicorn src.app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/demo
```

## Demo Workflow

1. Click Seed Demo Data.
   - Expected: `POST /demo/seed` returns 200.
   - Confirm recent cases and queue summary refresh with representative pending, reviewed, urgent, routine, and needs-follow-up cases.
2. Click Load Recent Cases.
   - Expected: `GET /cases?limit=10` returns 200.
   - confirm recent cases refresh and seeded cases are visible in the nurse queue.
3. Click Load Queue Summary.
   - Expected: `GET /cases/summary` returns 200.
   - Confirm summary counts reflect the seeded demo cases.
4. Select or copy a seeded case id from Recent Cases.
5. In Nurse Review, mark a case reviewed.
   - Expected: `POST /cases/{case_id}/review` returns 200.
   - confirm the reviewed state is visible in the returned case and recent cases after refresh.
6. Optionally submit a text intake from the Text Intake panel.
   - Expected: `POST /intake/text` returns 200.
   - The Last Created Case section shows a case id and pending review state.
7. reset the demo.
   - Expected: `POST /demo/reset` returns 200.
   - Confirm the demo returns to the expected clean state: recent cases are empty and summary counts return to zero.

## Notes

- This is for local demoability only.
- Mock mode sends no real email or SMS.
- Do not use this demo for medical advice or emergencies.
