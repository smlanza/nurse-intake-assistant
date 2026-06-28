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

The Demo Workflow list is clickable navigation. Its step numbers match the
visible section numbers on the page.

1. Click Seed Demo Data.
   - Expected: `POST /demo/seed` returns 200.
   - Confirm recent cases and queue summary refresh with representative pending, reviewed, urgent, routine, and needs-follow-up cases.
2. Click Load Recent Cases.
   - Expected: `GET /cases?limit=10` returns 200.
   - confirm recent cases refresh and seeded cases are visible in the nurse queue.
3. Click Load Queue Summary.
   - Expected: `GET /cases/summary` returns 200.
   - Confirm summary counts reflect the seeded demo cases.
4. Click Select for Review on a seeded case from Recent Cases.
   - Expected: the Nurse Review case id field is populated.
   - Confirm the page jumps to Nurse Review, focuses the case id field, and shows a selected-case status message.
   - Confirm the reviewNotes field is clear before entering notes for the selected case.
5. In Nurse Review, mark a case reviewed.
   - Expected: `POST /cases/{case_id}/review` returns 200.
   - confirm the reviewed state is visible in the returned case.
   - Confirm Recent Cases and Queue Summary refresh automatically after the review is saved.
   - Confirm Recent Cases shows reviewedBy, reviewedAt, and reviewNotes for the reviewed case when present.
6. Optionally submit a text intake from the Text Intake panel.
   - Expected: `POST /intake/text` returns 200.
   - The Last Created Case section shows a case id and pending review state.
7. Click Load Mock Email Notifications and Load Mock SMS Notifications.
   - Expected: `GET /notifications/email` and `GET /notifications/sms` return 200.
   - Confirm recorded mock notifications are shown, or friendly empty states appear when none are recorded.
   - Confirm mock mode sends no real email or SMS.
8. reset the demo.
   - Expected: `POST /demo/reset` returns 200.
   - Confirm the demo returns to the expected clean state: recent cases are empty, summary counts return to zero, and mock notification records are cleared.

## Notes

- This is for local demoability only.
- Mock mode sends no real email or SMS.
- Do not use this demo for medical advice or emergencies.
