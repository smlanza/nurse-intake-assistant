Nurse Intake Assistant - Capstone MVP Requirements

Purpose

Provide an AI-powered nurse intake system that collects patient information from phone calls, summarizes the request, determines urgency, and notifies a nurse for review.

⸻

Business Problem

Nurses spend significant time collecting patient information and documenting calls before they can assess patient needs.

The system will automate intake and documentation while ensuring that all clinical decisions remain with the nurse.

⸻

Users

Patient

Calls the intake line and provides information.

Nurse

Receives intake notifications and reviews patient requests.

⸻

Functional Requirements

FR-1 Phone Intake

The system shall answer incoming patient calls.

The system shall collect:

* Patient name
* Date of birth
* Callback number
* Reason for calling
* Symptoms

⸻

FR-2 Speech Transcription

The system shall convert patient speech into text.

The complete transcript shall be stored.

⸻

FR-3 AI Summary Generation

The system shall generate a structured summary containing:

* Patient information
* Reason for calling
* Symptoms
* Brief summary

⸻

FR-4 Urgency Classification

The system shall classify requests as:

* Routine
* Urgent

The urgency level is advisory and shall not replace nurse judgment.

⸻

FR-5 Case Creation

The system shall create a case record containing:

* Patient name
* DOB
* Callback number
* Transcript
* Summary
* Urgency level
* Timestamp

⸻

FR-6 Nurse Notification

The system shall notify the nurse when a new case is created.

Notification methods:

* SMS
* Email

⸻

FR-7 Nurse Review

The nurse shall be able to view:

* Patient information
* Transcript
* AI summary
* Urgency classification

⸻

FR-8 Review Completion

The nurse shall be able to mark a case as:

* Reviewed

⸻

Non-Functional Requirements

NFR-1 Human Review

The system shall not make medical decisions.

The nurse shall remain responsible for all patient follow-up.

⸻

NFR-2 Reliability

All case information shall be stored before notifications are sent.

⸻

NFR-3 Auditability

All transcripts and summaries shall be retained for demonstration purposes.

⸻

Success Criteria

A patient call results in:

1. Information collection
2. Speech transcription
3. AI summary generation
4. Urgency classification
5. Case creation
6. Nurse notification
7. Nurse review

without manual data entry by the nurse.