# PRAHARI: Mine Compliance & Risk Intelligence

## Overview

PRAHARI is a comprehensive compliance tracking and risk intelligence platform designed for mining environments. Built for safety inspectors and administrative officers, the application streamlines field reporting, ensures evidence integrity, and automatically maps on-site hazards to official mining regulations.

## Key Features

* **Centralized Dashboard Monitoring**
Track compliance statuses, open cases, and risk factors across multiple mining sites (e.g., underground collieries and opencast mines) from a single administrative interface.
* **Offline-First Field App**
Conduct inspections deep underground where internet connectivity is unavailable. The app allows inspectors to log details, attach photos, and queue their reports locally. Data syncs automatically to the main database once the network is restored.
* **AI-Powered Clause Mapping**
Utilizes AI to read inspector observations (such as "methane reading high") and instantly suggests the corresponding regulatory violation (e.g., *Coal Mines Regulations 2017*). It automatically assigns a severity level and recommends immediate corrective actions.
* **Automated Evidence Verification**
Ensures all photographic evidence submitted by inspectors is authentic. The system scans uploads to detect duplicate or tampered photos. If fraudulent evidence is detected, it flags the submission and automatically opens an "Evidence integrity review" case.
* **Immutable Audit Log**
Maintains a secure, tamper-proof timeline of all case activities. It tracks exactly when a case was created, when actions were taken, and when an officer ultimately approved and closed the ticket.

## Standard Workflow

1. **Observe & Record**: An inspector uses the field app to log a safety hazard and upload a photo of the issue.
2. **AI Assessment**: The app analyzes the text, assigns the correct regulatory clause, and dictates the required safety response (e.g., "Withdraw persons, restore ventilation").
3. **Queue & Sync**: If underground, the inspector saves the report offline. Upon returning to the surface, the app syncs the queue to the server.
4. **Verify Integrity**: The system checks the uploaded photo. If verified, a standard compliance case is opened. If tampered, an integrity review is launched.
5. **Resolve & Close**: Site workers resolve the hazard, and an authorized officer reviews the audit chain to officially close the case.
