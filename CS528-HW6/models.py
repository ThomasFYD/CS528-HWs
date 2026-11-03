"""Train-only feature learning and fixed, reproducible held-out evaluations."""
import random
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

import config as C

FEATURES = ["age", "gender", "country", "hour"]


def majority(counts):
    return sorted(counts, key=lambda label: (-counts[label], label))[0]


class PrefixCountry:
    """Learn /24 country modes; back off to /16, /8, then the training prior."""
    def fit(self, ips, countries):
        self.maps = {}
        self.prior = majority(Counter(countries))
        for length in (3, 2, 1):
            groups = defaultdict(Counter)
            for ip, country in zip(ips, countries):
                groups[".".join(ip.split(".")[:length])][country] += 1
            self.maps[length] = {key: majority(counts) for key, counts in groups.items()}
        return self

    def predict_with_level(self, ips):
        predictions, levels = [], []
        for ip in ips:
            for length in (3, 2, 1):
                key = ".".join(ip.split(".")[:length])
                if key in self.maps[length]:
                    predictions.append(self.maps[length][key]); levels.append(length * 8)
                    break
            else:
                predictions.append(self.prior); levels.append(0)
        return predictions, levels


class AgeMode(ClassifierMixin, BaseEstimator):
    """Categorical model: most common training income in each age group."""
    def fit(self, X, y):
        groups = defaultdict(Counter)
        for age, label in zip(X["age"], y):
            groups[age][label] += 1
        self.mapping_ = {age: majority(counts) for age, counts in groups.items()}
        self.prior_ = majority(Counter(y))
        self.classes_ = np.array(sorted(set(y)))
        return self

    def predict(self, X):
        return np.array([self.mapping_.get(age, self.prior_) for age in X["age"]])


def candidates():
    return {
        "age_mode": AgeMode(),
        "random_forest": make_pipeline(
            OneHotEncoder(handle_unknown="ignore"),
            RandomForestClassifier(n_estimators=120, max_depth=18, min_samples_leaf=20,
                                   max_features=0.8, n_jobs=2, random_state=C.SEED)),
        "hist_gradient_boosting": make_pipeline(
            OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
            HistGradientBoostingClassifier(categorical_features=[True] * 4,
                max_iter=150, max_leaf_nodes=15, learning_rate=0.08,
                l2_regularization=10, early_stopping=True, random_state=C.SEED)),
    }


def income_split(rows):
    # This exact partition was fixed before candidate evaluation.
    ordered = sorted(rows, key=lambda r: r["request_id"])
    random.Random(C.SEED).shuffle(ordered)
    n = len(ordered)
    return ordered[:int(n * .6)], ordered[int(n * .6):int(n * .8)], ordered[int(n * .8):]


def features(rows):
    return pd.DataFrame([{**{k: r[k] for k in FEATURES if k != "hour"},
                          "hour": r["client_time"][11:13]} for r in rows], columns=FEATURES)


def evaluate(y, predicted):
    labels = sorted(set(y) | set(predicted))
    n = len(y)
    p = float(accuracy_score(y, predicted))
    z = 1.96
    center = (p + z*z/(2*n))/(1+z*z/n)
    margin = z*((p*(1-p)/n + z*z/(4*n*n))**.5)/(1+z*z/n)
    return {"accuracy": p, "correct": int(sum(a == b for a, b in zip(y, predicted))),
            "test_rows": n, "wilson_95_interval": [center-margin, center+margin],
            "labels": labels, "confusion_matrix": confusion_matrix(y, predicted, labels=labels).tolist(),
            "classification_report": classification_report(y, predicted, labels=labels, output_dict=True, zero_division=0)}


def train_models(rows, output):
    output.mkdir(parents=True, exist_ok=True)
    # Group country holdout by exact IP: no repeated IP can leak across splits.
    ips = sorted({r["client_ip"] for r in rows})
    random.Random(C.SEED).shuffle(ips)
    train_ips = set(ips[:int(len(ips)*.8)])
    country_train = sorted((r for r in rows if r["client_ip"] in train_ips), key=lambda r:r["request_id"])
    country_test = sorted((r for r in rows if r["client_ip"] not in train_ips), key=lambda r:r["request_id"])
    country_model = PrefixCountry().fit([r["client_ip"] for r in country_train], [r["country"] for r in country_train])
    country_pred, levels = country_model.predict_with_level([r["client_ip"] for r in country_test])
    country_scores = evaluate([r["country"] for r in country_test], country_pred)
    country_scores.update(model="training-only IP prefix majority with backoff", train_rows=len(country_train),
                          train_unique_ips=len(train_ips), test_unique_ips=len(ips)-len(train_ips),
                          shared_ips=0, target_accuracy=.99,
                          target_met=country_scores["accuracy"] >= .99,
                          prefix_levels=dict(Counter(levels)))
    pd.DataFrame([{"request_id":r["request_id"], "client_ip":r["client_ip"],
                   "actual_country":r["country"], "predicted_country":p,
                   "matched_prefix_bits":l, "correct":r["country"]==p}
                  for r,p,l in zip(country_test,country_pred,levels)]).to_csv(output/"country_predictions.csv",index=False)
    print(f"Country held-out accuracy: {country_scores['accuracy']:.4%}", flush=True)

    train, validation, test = income_split(rows)
    xtrain, xval = features(train), features(validation)
    ytrain, yval = [r["income"] for r in train], [r["income"] for r in validation]
    validation_scores = {}
    for name, model in candidates().items():
        model.fit(xtrain, ytrain)
        validation_scores[name] = float(accuracy_score(yval, model.predict(xval)))
        print(f"Income validation {name}: {validation_scores[name]:.4%}", flush=True)
    # Deterministic tie handling favors the earlier, simpler candidate.
    chosen = max(validation_scores, key=validation_scores.get)
    final = candidates()[chosen]
    final.fit(features(train+validation), [r["income"] for r in train+validation])
    predicted = final.predict(features(test)).tolist()
    ytest = [r["income"] for r in test]
    income_scores = evaluate(ytest, predicted)
    baseline = majority(Counter(r["income"] for r in train+validation))
    income_scores.update(model=chosen, features=["age"] if chosen == "age_mode" else FEATURES,
        validation_scores=validation_scores, selection_train_rows=len(train), validation_rows=len(validation),
        final_train_rows=len(train)+len(validation), target_accuracy=.35,
        target_met=income_scores["accuracy"]>=.35,
        majority_baseline_accuracy=float(accuracy_score(ytest,[baseline]*len(test))),
        test_policy="Fixed request-level 60/20/20 split; select on validation; refit on 80%; evaluate test once",
        notes="Income labels are ranges, evaluated by exact category accuracy. No income-derived features, IDs, timestamps of receipt, or test labels enter training. Rows may share IPs; IP is not an income feature.")
    if chosen == "age_mode": income_scores["learned_age_mapping"] = final.mapping_
    pd.DataFrame([{"request_id":r["request_id"], **features([r]).iloc[0].to_dict(),
                   "actual_income":r["income"], "predicted_income":p, "correct":r["income"]==p}
                 for r,p in zip(test,predicted)]).to_csv(output/"income_predictions.csv",index=False)
    pd.DataFrame([{"model":"country","request_id":r["request_id"],"split":"train" if r["client_ip"] in train_ips else "test"} for r in rows]
        + [{"model":"income","request_id":r["request_id"],"split":split} for split, part in (("train",train),("validation",validation),("test",test)) for r in part]).to_csv(output/"splits.csv",index=False)
    print(f"Income selected {chosen}; held-out accuracy: {income_scores['accuracy']:.4%}",flush=True)
    return {"seed":C.SEED,"country":country_scores,"income":income_scores}
