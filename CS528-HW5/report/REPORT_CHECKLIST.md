# Evidence required before the final HW5 PDF

Status: 61 offline tests passed (final user output); both VM startup logs verified;
real curl 200/404/400, the 200-request smoke run and formal 100,000-request run
passed. Raw formal results were independently verified. Cloud execution/delivery evidence and teardown were reviewed. All 9 curl replay screenshots are collected and reviewed. Billing scope was confirmed by the owner. The final 18-page PDF was generated and every rendered page passed visual review.
The author confirmed CS528-HW5 as the final directory.

- [x] Inspect all four pages of the HW5 assignment and the updated-client notice.
- [x] Confirm the supplied client is macOS ARM64 and observe its actual headers.
- [x] Preserve the unmodified HW4 reporter and verify its SHA-256.
- [x] Initial `verify_local.sh`: 38 tests passed (user-reported output).
- [x] Final `verify_local.sh`: 61 tests passed in 11.943 seconds; no cloud resources created.
- [x] Recheck after deployment and driver corrections: 51 tests passed; full output retained.
- [x] Review `setup.sh --plan` and authenticate GCP.
- [x] Run setup from a fresh deployment; verify web/reporter startup and SQL tables.
- [ ] Verify setup reuse without destroying data and reboot without reinstalling.
- [x] Verify real curl 200/404/400 and saved before/after SQL data (demo-8131a0d413fb4069).
- [x] Collect and visually review 9 user-captured screenshots of local replay of saved real curl evidence; retain explicit replay captions.
- [x] Verify subscription delivery/acknowledgment activity and empty sampled backlog; individual Reporter stdout was not collected.
- [x] Run two clients with 100 requests each and reconcile all SQL records (load-20261021T074356Z-c17a9e06).
- [x] Run two clients with 50,000 requests each, identical seed, updated client binary.
- [x] Review both exit codes, actual counts, timings and expected banned-country errors.
- [x] Prepare six statistical answers in `report/EXPERIMENT_RESULTS.md`; transfer to final PDF.
- [x] Explain timing boundaries and skipped reads in `report/EXPERIMENT_RESULTS.md`; transfer to final PDF.
- [x] Verify hourly guard STOP_INSTANCE audit completion and post-run ENABLED state.
- [x] Export evidence before cleanup; verify SQL STOPPED/NEVER, VMs removed, static IP released and scheduler removed.
- [x] Record October 20-22 billing snapshot: displayed net $0.00 with $1.61 savings; owner confirmed no gcloud work on other projects; preserve capture-time limits.
- [x] Create the final 18-page PDF and visually inspect every rendered page; numerical results match verified evidence.
- [x] Use repository directory `CS528-HW5`, as explicitly confirmed by the author.

Publication checks are enforced by the release command: only reviewed HW5 files
and the repository README are staged, shell scripts use Git mode 100755, and
the remote main commit is checked after push.
