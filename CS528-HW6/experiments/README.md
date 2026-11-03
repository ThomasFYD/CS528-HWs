# Income optimization follow-up

The 35% aim was not reached. This local experiment leaves the submitted cloud
model and its 34.27% result unchanged.

The original seed (528) and 60,000 / 20,000 / 20,000 partition were retained.
Only the training and validation partitions were used for the 27 recorded
development configurations: nine smoothed category models, six histogram
gradient-boosting models, two Extra Trees models, six CatBoost models, and four
age-relative income classifiers. Preliminary feature checks and three-fold
training diagnostics are separate from these 27 configurations.

The best validation result was CatBoost at 34.590%. Its depth (4), learning
rate (0.05), L2 penalty (10) and tree count (99, chosen by validation early
stopping) were frozen before the follow-up test. It used age, gender, country
and simulated hour. Refitting on the original 80,000 training + validation
rows produced **33.295% (6,659 / 20,000)** on the original test set. Test IDs,
ordering and true labels were checked against the published cloud output.
No other follow-up candidate was tested after this result.

The original test had already been used for the published random-forest
evaluation; this follow-up is not a newly collected independent test set.
Selection used validation scores only. The best validation score after many
comparisons can be optimistic. The selected configuration's three-fold
accuracy on the original training partition averaged 33.427%.

In the original training partition, each age group had three income labels
with nearly equal frequencies. Extra fields and the alternative models did
not establish a reliable improvement. This is an empirical limitation, not
proof that 35% is mathematically impossible.

`../report/evidence/income-optimization.json` contains all 27 scores, their
configurations, diagnostics, the final confusion matrix and data checksums.
`income-selection-frozen.json` preserves the exact selection made before the
test, including its timestamp and parameters. The original follow-up prediction
CSV is retained locally under `results/income-optimization-local/`; it is not
presented as VM output or substituted for the bucket's measured predictions.

To reproduce only the frozen candidate from the HW6 directory:

```bash
.venv/bin/pip install -r experiments/requirements.txt
.venv/bin/python experiments/evaluate_income_candidate.py \
  --snapshot ../CS528-HW5/results/load-20261021T075735Z-5b3f60c2/database-snapshot.json.gz \
  --output results/income-candidate-reproduction
```

Use a new output directory. The script verifies the original snapshot,
selection and test-membership checksums. It does not start cloud resources.
