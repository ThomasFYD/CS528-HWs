#!/usr/bin/env python3
"""Build a plain black-and-white HW6 report from measured outputs."""
import argparse
import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Preformatted

ROOT=Path(__file__).resolve().parent
WIDTH=504
# HW4's typography and section structure, with plain black text on white pages.
# No preset stylesheet, theme, shaded cells, or decorative page rules.
styles={
    'BodyHW': ParagraphStyle('BodyHW',fontName='Helvetica',fontSize=9.4,leading=13,spaceAfter=8,textColor=colors.black),
    'SmallHW': ParagraphStyle('SmallHW',fontName='Helvetica',fontSize=8.2,leading=11,spaceAfter=6,textColor=colors.black),
    'TitleHW': ParagraphStyle('TitleHW',fontName='Helvetica-Bold',fontSize=22,leading=27,spaceAfter=12,textColor=colors.black),
    'HeadHW': ParagraphStyle('HeadHW',fontName='Helvetica-Bold',fontSize=16,leading=20,spaceAfter=12,textColor=colors.black),
    'SubHW': ParagraphStyle('SubHW',fontName='Helvetica-Bold',fontSize=11,leading=14,spaceBefore=9,spaceAfter=6,textColor=colors.black),
    'CodeHW': ParagraphStyle('CodeHW',fontName='Courier',fontSize=7.5,leading=9.3,spaceAfter=10,textColor=colors.black),
    'CellHW': ParagraphStyle('CellHW',fontName='Helvetica',fontSize=8.1,leading=10.5,textColor=colors.black),
}


def para(text,style='BodyHW'): return Paragraph(text,styles[style])
def title(text): return para(text,'HeadHW')
def sub(text): return para(text,'SubHW')
def table(rows,widths):
    converted=[[para(('<b>'+escape(str(cell))+'</b>') if i==0 else escape(str(cell)),'CellHW')
                for cell in row] for i,row in enumerate(rows)]
    result=Table(converted,colWidths=widths,repeatRows=1,hAlign='LEFT')
    result.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--date',default='November 3, 2026',help='Printed report date')
    args=parser.parse_args()
    result=args.results
    metrics=json.loads((result/'metrics.json').read_text())
    audit=json.loads((result/'migration.json').read_text())
    cleanup=json.loads((result/'cleanup.json').read_text()) if (result/'cleanup.json').exists() else {}
    cloud=metrics['mode']=='CLOUD_SQL_ON_VM' and bool(cleanup.get('verified')) and bool(audit.get('lossless'))
    country,income=metrics['country'],metrics['income']
    optimization_path=ROOT/'report'/'evidence'/'income-optimization.json'
    optimization=json.loads(optimization_path.read_text()) if optimization_path.exists() else None
    if optimization and optimization['baseline_output_uri'] != metrics.get('output_uri'):
        optimization=None
    output=ROOT/'report'/'CS528_HW6_Report.pdf';output.parent.mkdir(exist_ok=True)
    story=[]
    story += [para('CS528 Homework 6','TitleHW'),
              para('Database Normalization and Predictive Models','HeadHW'),
              para('<b>Yide Fang</b> | Boston University | '+escape(args.date)),
              para('Code: <link href="https://github.com/ThomasFYD/CS528-HWs">https://github.com/ThomasFYD/CS528-HWs</link><br/>Directory: <b>CS528-HW6</b>'),
              sub('1. Design, data and measured results'),
              para('I used the complete formal HW5 experiment: 100,000 requests, 76,603 distinct client IPs and 197 country labels. The source run is <b>load-20261021T075735Z-5b3f60c2</b>. Other HW5 tests remain in the original database.'),
        para('The implementation creates four normalized base tables in a separate <b>hw6</b> database on the preserved Cloud SQL instance. It verifies that joining the tables reconstructs every original field before committing the data migration.'),
        table([['Model','Held-out accuracy','Result'],
            ['Client IP to country',f"{country['accuracy']:.2%} ({country['correct']:,}/{country['test_rows']:,})",'Meets the 99% requirement' if country['target_met'] else 'Below 99%'],
            ['Available fields to income',f"{income['accuracy']:.2%} ({income['correct']:,}/{income['test_rows']:,})",'Meets the 35% aim' if income['target_met'] else 'Below the 35% aim; limitation reported']], [155,160,WIDTH-315]),
        Spacer(1,9),
        para('Country prediction uses a learned IP-prefix classifier. Income prediction compares three candidates on a separate validation set and evaluates the selected model on a fixed test set. The seed is 528. Section 5 explains both models, the partitions and the income result.'),
        sub('Execution and retained evidence')]
    if cloud:
        story += [para('The models were run on a newly created VM against Cloud SQL. Source and reconstructed record hashes match. Output downloads passed SHA-256 checks. Cleanup verified that SQL was stopped and the temporary VM and network were removed.'),
                  para('Bucket output: '+escape(metrics['output_uri']),'SmallHW')]
    else:
        story += [para('<b>Draft: these results do not yet establish a completed cloud run.</b> A local snapshot result or an incomplete cleanup record does not verify SQL migration, VM execution, bucket uploads and cloud cleanup.'),
            para('Planned output: gs://cs528-hw2-yf-2026/cs528-hw6/runs/&lt;run-id&gt;/','SmallHW')]
    story += [para('Source, lifecycle scripts and measured-run evidence are provided in <link href="https://github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW6">CS528-HW6</link>. The report/evidence directory contains the migration checks, model metrics, output hashes and cleanup record. Full prediction files and split membership are retained in the bucket.'),
              sub('Scope of the result'),para('The country result reflects instructor-generated IP patterns. The income result is below the assignment aim and is reported without changing the test partition or seed. The original HW5 tables and the normalized HW6 database are retained for inspection; the temporary compute resources have been removed.' if cloud else 'The local measurements are retained for development. Cloud completion requires both VM output evidence and a verified cleanup record.'),PageBreak()]

    story += [title('2. Functional dependencies and 3NF'),
        para('The original request table has the transitive dependency <b>request_id -&gt; client_ip -&gt; country -&gt; is_banned</b>. It also stores <b>client_time -&gt; time_of_day</b>. These determinants are not request-table candidate keys, so the original table is not in 3NF.'),
        table([['Base table / key','Stored attributes and dependency'],
            ['countries / country','is_banned; country determines the fixed homework policy flag.'],
            ['clients / client_ip','country (FK); a simulated client IP determines exactly one country.'],
            ['requests / request_id; request_time is also UNIQUE','request_time, run_id, method, requested_file, client_ip (FK), peer_ip, gender, age, income, client_time, http_status. Each value describes a request.'],
            ['request_timings / request_id (PK and FK)','extract_ns, storage_ns, response_ns, database_ns, total_ns, storage_attempted, response_sent. One row per request.']], [158,WIDTH-158]),
        Spacer(1,12),para('All stored values are atomic for their intended domain. Each primary key is a single attribute, so there are no partial key dependencies. Under the assignment assumptions, every non-key attribute in each base table depends on a candidate key, with the identified transitive dependencies removed. Age and income ranges are categorical values; IP is not assumed to determine a client\'s demographic attributes.'),
        sub('Derived values and failure records'),para('The request_details view joins requests, clients and countries, and derives time_of_day from client_time. The failed_requests view derives non-200 request rows. The old failure table has its own valid key, but copying file/status values into another stored table is unnecessary here. Source error rows are checked for exact agreement with the view.'),
        sub('Data-transfer safeguards'),para('Before migration, the program rejects missing metadata, conflicting IP-country pairs, inconsistent country-policy flags, duplicate keys, mismatched derived times, inconsistent failures and missing timing records. The formal run contains zero IP-country conflicts and zero missing required fields.'),
        para('Data INSERTs share one transaction. SHA-256 fingerprints cover every field of reconstructed requests, failures and timings, with canonical ordering and MySQL boolean/date normalization. A mismatch rolls back the new INSERTs. Existing rows are retained and checked on rerun. MySQL DDL runs separately because it commits implicitly.'),PageBreak()]

    ddl,views=(ROOT/'schema.sql').read_text().split('-- Views',1)
    story += [title('3. MySQL schema'),para('The orchestration script first creates the hw6 database. The following DDL defines the normalized base tables.'),Preformatted(ddl.strip(),styles['CodeHW']),PageBreak()]
    # Keep the complete executable listings, including exact bound run scope.
    sql='-- Views'+views+'\n'+(ROOT/'migrate.sql').read_text()
    sql='\n'.join(line for line in sql.splitlines() if not line.startswith('--'))
    story += [title('4. Reconstruction and migration queries'),para('The runner binds :run_id to the formal HW5 run. MIN selects the single value only after functional-dependency validation; it does not resolve conflicts.'),Preformatted(sql.strip(),styles['CodeHW']),PageBreak()]

    story += [title('5. Models and held-out evaluation'),sub('Model 1: learned IP-prefix classifier'),
        para('The classifier learns the most frequent country for each /24 IPv4 prefix from training rows only. For an unseen prefix, it backs off to /16, /8, then the training majority. This is a learned categorical lookup model. It does not consult a full-data IP-country table when predicting test labels.'),
        para(f"With seed 528, 80% of sorted unique IPs are assigned to training and the remainder to test. This produces {country['train_rows']:,} training requests and {country['test_rows']:,} test requests, with <b>zero shared IPs</b>. Test accuracy is <b>{country['accuracy']:.2%}</b>. The result reflects instructor-generated IP patterns and is not evidence of real-world geolocation performance."),
        sub('Model 2: income-range classification'),
        para('Sort requests by ID and shuffle once using seed 528. Use 60,000 rows for candidate fitting, 20,000 for validation, and reserve 20,000 for final testing. Compare three fixed candidates. Select the highest validation accuracy, refit that model on the first 80,000 rows, and evaluate the fixed test set. No test labels, income-derived inputs or request IDs enter feature learning.'),
        table([['Candidate','Validation accuracy']]+[[name,f'{score:.3%}'] for name,score in income['validation_scores'].items()],[WIDTH-125,125]),
        Spacer(1,10),para('Random forest uses age, gender, country and simulated hour, one-hot encoding fitted only on training data, 120 trees, maximum depth 18, minimum 20 examples per leaf, max_features=0.8 and random seed 528. The alternatives are a training age-group mode and histogram gradient boosting with 150 iterations, 15 leaves, learning rate 0.08 and L2 penalty 10.'),
        para(f"The selected model is <b>{escape(income['model'])}</b>. Its test accuracy is <b>{income['accuracy']:.2%}</b>, versus a training-majority baseline of <b>{income['majority_baseline_accuracy']:.3%}</b>. Exact category matching is used. The approximate 95% Wilson interval is {income['wilson_95_interval'][0]:.2%} to {income['wilson_95_interval'][1]:.2%}; repeated demographic patterns mean the usual independent-trial interval should be interpreted cautiously."),
        sub('Income target and limitations'),para(f"The measured result is {max(0,.35-income['accuracy'])*100:.2f} percentage points below the 35% aim. The assignment warns that generated data and the random seed can affect fitting. The seed and test partition were kept fixed. The compared models do not establish a theoretical accuracy ceiling.")]
    if optimization:
        followup=optimization['final_evaluation']
        best=followup['selection']['selected_trial']
        story += [sub('Additional local optimization'),
            para(f"A follow-up compared {optimization['trial_count']} configurations on the original training and validation partitions, including additional field combinations, Extra Trees and CatBoost. The best validation score was <b>{best['validation_accuracy']:.3%}</b> (CatBoost, depth 4, {best['iterations']} trees). Its settings were frozen, then refitted on 80,000 rows. One follow-up evaluation on the original test set scored <b>{followup['accuracy']:.3%} ({followup['correct']:,}/{followup['test_rows']:,})</b>. This local result did not improve the published cloud model; the original model and bucket outputs are retained.",'SmallHW'),
            para('The test set had already been used for the original model; it is not a new independent holdout. Only training/validation data guided this search. Each training age group had three nearly equally frequent income labels; added fields did not show reliable improvement. All 27 scores, settings, diagnostics and final-test checksums are in report/evidence/income-optimization.json.','SmallHW')]
    story.append(PageBreak())

    story += [title('6. Configuration, execution and cleanup'),
        para('Required local tools: Google Cloud CLI and Python 3.11 or 3.12. Authenticate with an authorized project identity; the owner uses fangyd@bu.edu. Every cloud command pins project dazzling-seat-508219-j3.'),
        Preformatted('gcloud auth login fangyd@bu.edu\ncd CS528-HW6\npython3 infra.py plan\npython3 infra.py preflight\nbash run.sh',styles['CodeHW']),Spacer(1,10),
        table([['Setting','Value'],['Existing SQL','cs528-hw5-mysql; MySQL 8.4; source hw5; target hw6'],['VM','Temporary e2-standard-2; Debian 12; 10 GB standard boot disk'],['Location','us-central1-a; dedicated temporary VPC and subnet'],['Password','Secret Manager: cs528-hw5-db-password; no committed key'],['Output bucket','gs://cs528-hw2-yf-2026'],['Identity','cs528-hw6-worker; Cloud SQL Client, one secret, scoped storage access']],[110,WIDTH-110]),
        Spacer(1,10),para('The script checks that SQL is stopped, prepares the identity, uploads a source archive, starts SQL and creates the VM. A startup script downloads the archive and validates its SHA-256, installs pinned dependencies, migrates SQL data and runs the models. No interactive SSH configuration is required. Predictions and evidence are uploaded under a unique run prefix; done.json is written last.'),
        para('The controller verifies downloaded output hashes, then stops SQL and deletes the VM with its boot disk, subnet and network. It prints summary.txt and both complete prediction CSVs from the downloaded bucket objects. SQL data, outputs, source archives and the reusable identity are retained. Stopped SQL still allocates storage.'),
        sub('Failure handling'),para('Exceptions, Ctrl-C and SIGTERM attempt cleanup. VM deletion is still attempted if stopping SQL fails. Network loss, forced process termination or expired authentication can prevent cleanup. Use the recorded run state to retry:'),
        Preformatted('python3 infra.py cleanup --state results/<run-id>/state.json',styles['CodeHW']),
        para('If uploads completed, use the resume action with the same --state path to recover verified outputs, cleanup and terminal printing without starting resources. The measured run required this recovery after a client-side timeout during VM deletion. The original error record is retained. Final cleanup.json must show verified=true.','SmallHW'),PageBreak()]

    story += [title('7. Output examples and evidence'),para('Each prediction file contains the request ID, actual label, predicted label and correctness. Country output also identifies the learned prefix length; income output includes the four candidate input fields.'),
              sub('Country prediction examples')]
    with (result/'country_predictions.csv').open() as f: example=list(csv.DictReader(f))[:5]
    story.append(table([['Client IP','Actual country','Prediction','Correct']]+[[r['client_ip'],r['actual_country'],r['predicted_country'],r['correct']] for r in example],[115,155,155,WIDTH-425]))
    story.append(sub('Income prediction examples'))
    with (result/'income_predictions.csv').open() as f: example=list(csv.DictReader(f))[:5]
    story.append(table([['Age','Actual income','Prediction','Correct']]+[[r['age'],r['actual_income'],r['predicted_income'],r['correct']] for r in example],[80,165,165,WIDTH-410]))
    story += [sub('Verification record'),para('Fifteen local tests passed: dependency conflicts, derived-value consistency, failed/timing record integrity, canonical hashes, repeatable SQL transfer, held-out split isolation, target-free features, prefix backoff, cleanup continuation, leftover disk detection, recovery failure handling and ownership checks. Python and shell syntax checks passed.'),
        para('Measured dependency versions: '+escape(', '.join(k+' '+v for k,v in metrics['versions'].items())),'SmallHW'),
        para('Full per-class reports, confusion matrices, partition membership and hashes are saved in metrics.json, splits.csv and migration.json. '+('Cloud cleanup has been verified.' if cloud else '<b>Cloud migration and cleanup evidence remain pending.</b>')),
        sub('Sources'),para('1. CS528-HW_6.pdf, assignment instructions supplied by the instructor.<br/>2. Cloud Computing (lecture 13) -- Database optimization.pdf, normal forms, slides 5, 7, 9 and 11.<br/>3. HW5 source schema and formal-run backup in CS528-HW5.<br/>4. <link href="https://scikit-learn.org/1.7/modules/ensemble.html">scikit-learn ensemble documentation</link>.<br/>5. <link href="https://docs.cloud.google.com/compute/docs/instances/startup-scripts/linux">Google Compute Engine Linux startup scripts</link>.','SmallHW')]

    def footer(canvas,doc):
        canvas.saveState();canvas.setFillColor(colors.black);canvas.setFont('Helvetica',8)
        if not cloud: canvas.drawString(54,27,'Draft')
        canvas.drawRightString(558,27,str(doc.page));canvas.restoreState()
    doc=SimpleDocTemplate(str(output),pagesize=(612,792),leftMargin=54,rightMargin=54,topMargin=44,bottomMargin=55,
                          title='CS528 Homework 6 - Yide Fang',author='Yide Fang')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    print(output)


if __name__=='__main__': main()
