#!/usr/bin/env python3
"""Build the HW6 report from measured outputs; never invent cloud evidence."""
import argparse
import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Preformatted

ROOT=Path(__file__).resolve().parent
WIDTH=7.25*inch
BLUE=colors.HexColor('#143B59')
TEAL=colors.HexColor('#087E8B')
PALE=colors.HexColor('#EDF4F7')
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyHW',fontName='Helvetica',fontSize=10,leading=14,spaceAfter=8,textColor=colors.HexColor('#253542')))
styles.add(ParagraphStyle(name='SmallHW',parent=styles['BodyHW'],fontSize=8.3,leading=11))
styles.add(ParagraphStyle(name='TitleHW',fontName='Helvetica-Bold',fontSize=27,leading=31,spaceAfter=14,textColor=BLUE))
styles.add(ParagraphStyle(name='HeadHW',fontName='Helvetica-Bold',fontSize=16,leading=20,spaceAfter=12,textColor=BLUE))
styles.add(ParagraphStyle(name='SubHW',fontName='Helvetica-Bold',fontSize=11,leading=15,spaceBefore=8,spaceAfter=7,textColor=TEAL))
styles.add(ParagraphStyle(name='CodeHW',fontName='Courier',fontSize=7.5,leading=9.8,textColor=colors.HexColor('#223443')))


def para(text,style='BodyHW'): return Paragraph(text,styles[style])
def title(text): return para(text,'HeadHW')
def sub(text): return para(text,'SubHW')
def table(rows,widths):
    converted=[[para(escape(str(cell)),'SmallHW') for cell in row] for row in rows]
    result=Table(converted,colWidths=widths,repeatRows=1,hAlign='LEFT')
    result.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LINEBELOW',(0,0),(-1,0),.7,TEAL),('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#D7E1E6')),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    args=parser.parse_args()
    result=args.results
    metrics=json.loads((result/'metrics.json').read_text())
    audit=json.loads((result/'migration.json').read_text())
    cleanup=json.loads((result/'cleanup.json').read_text()) if (result/'cleanup.json').exists() else {}
    cloud=metrics['mode']=='CLOUD_SQL_ON_VM' and bool(cleanup.get('verified')) and bool(audit.get('lossless'))
    status='CLOUD EXECUTION VERIFIED' if cloud else 'DRAFT - LOCAL VALIDATION; CLOUD EXECUTION PENDING'
    country,income=metrics['country'],metrics['income']
    output=ROOT/'report'/'CS528_HW6_Report.pdf';output.parent.mkdir(exist_ok=True)
    story=[]
    story += [para('CS528 Cloud Computing','SubHW'),para('Homework 6','TitleHW'),
              para('Database normalization and predictive models','HeadHW'),para('Yide Fang | Boston University'),
              para(status,'SubHW'),Spacer(1,12)]
    story.append(table([['Model','Held-out accuracy','Result'],
        ['Client IP to country',f"{country['accuracy']:.2%} ({country['correct']:,}/{country['test_rows']:,})",'Meets the 99% requirement' if country['target_met'] else 'Below 99%'],
        ['Available fields to income',f"{income['accuracy']:.2%} ({income['correct']:,}/{income['test_rows']:,})",'Meets the 35% aim' if income['target_met'] else 'Below the 35% aim; limitation reported']], [165,172,WIDTH-337]))
    story += [Spacer(1,15),sub('Experiment scope'),para('The input is the complete formal HW5 experiment: 100,000 requests, 76,603 distinct client IPs and 197 country labels. The source run is <b>load-20261021T075735Z-5b3f60c2</b>. Other HW5 tests remain in the original database.'),
        para('The implementation creates four normalized base tables in a separate <b>hw6</b> database on the preserved Cloud SQL instance. It verifies that joining the tables reconstructs every original field before committing the data migration.'),
        sub('Evidence status')]
    if cloud:
        story += [para('The models were run on a newly created VM against Cloud SQL. Source and reconstructed record hashes match. Output downloads passed SHA-256 checks. Cleanup verified that SQL was stopped and the temporary VM and network were removed.'),
                  para('Bucket output: '+escape(metrics['output_uri']),'SmallHW')]
    else:
        story += [para('<b>These are measured local results from the preserved HW5 data backup.</b> Google Cloud authentication expired. SQL migration, VM execution, bucket uploads and cloud cleanup have not yet been demonstrated; this PDF is not a completed cloud submission.'),
            para('Planned output: gs://cs528-hw2-yf-2026/cs528-hw6/runs/&lt;run-id&gt;/','SmallHW')]
    story += [sub('Code location'),para('<link href="https://github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW6" color="#087E8B">github.com/ThomasFYD/CS528-HWs/tree/main/CS528-HW6</link>','SmallHW'),
              para('Source, lifecycle scripts, the PDF report and measured-run evidence are provided in the CS528-HW6 directory.','SmallHW'),PageBreak()]

    story += [title('1. Functional dependencies and 3NF'),
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
    story += [title('2. MySQL schema'),para('The orchestration script first creates the hw6 database. The following DDL defines the normalized base tables.','SmallHW'),Preformatted(ddl.strip(),styles['CodeHW']),PageBreak()]
    # Keep the complete executable listings, including exact bound run scope.
    sql='-- Views'+views+'\n'+(ROOT/'migrate.sql').read_text()
    sql='\n'.join(line for line in sql.splitlines() if not line.startswith('--'))
    story += [title('3. Reconstruction and migration queries'),para('The runner binds :run_id to the formal HW5 run. MIN selects the single value only after functional-dependency validation; it does not resolve conflicts.','SmallHW'),Preformatted(sql.strip(),styles['CodeHW']),PageBreak()]

    story += [title('4. Models and held-out evaluation'),sub('Model 1: learned IP-prefix classifier'),
        para('The classifier learns the most frequent country for each /24 IPv4 prefix from training rows only. For an unseen prefix, it backs off to /16, /8, then the training majority. This is a learned categorical lookup model. It does not consult a full-data IP-country table when predicting test labels.'),
        para(f"With seed 528, 80% of sorted unique IPs are assigned to training and the remainder to test. This produces {country['train_rows']:,} training requests and {country['test_rows']:,} test requests, with <b>zero shared IPs</b>. Test accuracy is <b>{country['accuracy']:.2%}</b>. The result reflects instructor-generated IP patterns and is not evidence of real-world geolocation performance."),
        sub('Model 2: income-range classification'),
        para('Sort requests by ID and shuffle once using seed 528. Use 60,000 rows for candidate fitting, 20,000 for validation, and reserve 20,000 for final testing. Compare three fixed candidates. Select the highest validation accuracy, refit that model on the first 80,000 rows, and evaluate the fixed test set. No test labels, income-derived inputs or request IDs enter feature learning.'),
        table([['Candidate','Validation accuracy']]+[[name,f'{score:.3%}'] for name,score in income['validation_scores'].items()],[WIDTH-125,125]),
        Spacer(1,10),para('Random forest uses age, gender, country and simulated hour, one-hot encoding fitted only on training data, 120 trees, maximum depth 18, minimum 20 examples per leaf, max_features=0.8 and random seed 528. The alternatives are a training age-group mode and histogram gradient boosting with 150 iterations, 15 leaves, learning rate 0.08 and L2 penalty 10.'),
        para(f"The selected model is <b>{escape(income['model'])}</b>. Its test accuracy is <b>{income['accuracy']:.2%}</b>, versus a training-majority baseline of <b>{income['majority_baseline_accuracy']:.3%}</b>. Exact category matching is used. The approximate 95% Wilson interval is {income['wilson_95_interval'][0]:.2%} to {income['wilson_95_interval'][1]:.2%}; repeated demographic patterns mean the usual independent-trial interval should be interpreted cautiously."),
        sub('Income target and limitations'),para(f"The measured result is {max(0,.35-income['accuracy'])*100:.2f} percentage points below the 35% aim. Age contains useful signal; the compared combinations of other fields did not reliably reach the target. The assignment warns that the generated data and random seed can affect fitting. This observation does not prove that a better model cannot exist. The seed and test partition were not changed after evaluation to improve the displayed score."),PageBreak()]

    story += [title('5. Configuration, execution and cleanup'),
        para('Required local tools: Google Cloud CLI and Python 3.11 or 3.12. Authenticate with an authorized project identity; the owner uses fangyd@bu.edu. Every cloud command pins project dazzling-seat-508219-j3.'),
        Preformatted('gcloud auth login fangyd@bu.edu\ncd CS528-HW6\npython3 infra.py plan\npython3 infra.py preflight\nbash run.sh',styles['CodeHW']),Spacer(1,10),
        table([['Setting','Value'],['Existing SQL','cs528-hw5-mysql; MySQL 8.4; source hw5; target hw6'],['VM','Temporary e2-standard-2; Debian 12; 10 GB standard boot disk'],['Location','us-central1-a; dedicated temporary VPC and subnet'],['Password','Secret Manager: cs528-hw5-db-password; no committed key'],['Output bucket','gs://cs528-hw2-yf-2026'],['Identity','cs528-hw6-worker; Cloud SQL Client, one secret, scoped storage access']],[110,WIDTH-110]),
        Spacer(1,10),para('The script checks that SQL is stopped, prepares the identity, uploads a source archive, starts SQL and creates the VM. A startup script downloads the archive and validates its SHA-256, installs pinned dependencies, migrates SQL data and runs the models. No interactive SSH configuration is required. Predictions and evidence are uploaded under a unique run prefix; done.json is written last.'),
        para('The controller verifies downloaded output hashes, then stops SQL and deletes the VM with its boot disk, subnet and network. It prints summary.txt and both complete prediction CSVs from the downloaded bucket objects. SQL data, outputs, source archives and the reusable identity are retained. Stopped SQL still allocates storage.'),
        sub('Failure handling'),para('Exceptions, Ctrl-C and SIGTERM attempt cleanup. VM deletion is still attempted if stopping SQL fails. Network loss, forced process termination or expired authentication can prevent cleanup. Use the recorded run state to retry:'),
        Preformatted('python3 infra.py cleanup --state results/<run-id>/state.json',styles['CodeHW']),
        para('If uploads completed, use the resume action with the same --state path to recover verified outputs, cleanup and terminal printing without starting resources. The measured run required this recovery after a client-side timeout during VM deletion. The original error record is retained. Final cleanup.json must show verified=true.','SmallHW'),PageBreak()]

    story += [title('6. Output examples and evidence'),para('Each prediction file contains the request ID, actual label, predicted label and correctness. Country output also identifies the learned prefix length; income output includes the four candidate input fields.'),
              sub('Country prediction examples')]
    with (result/'country_predictions.csv').open() as f: example=list(csv.DictReader(f))[:5]
    story.append(table([['Client IP','Actual country','Prediction','Correct']]+[[r['client_ip'],r['actual_country'],r['predicted_country'],r['correct']] for r in example],[115,155,155,WIDTH-425]))
    story.append(sub('Income prediction examples'))
    with (result/'income_predictions.csv').open() as f: example=list(csv.DictReader(f))[:5]
    story.append(table([['Age','Actual income','Prediction','Correct']]+[[r['age'],r['actual_income'],r['predicted_income'],r['correct']] for r in example],[80,165,165,WIDTH-410]))
    story += [sub('Verification record'),para('Fifteen local tests passed: dependency conflicts, derived-value consistency, failed/timing record integrity, canonical hashes, repeatable SQL transfer, held-out split isolation, target-free features, prefix backoff, cleanup continuation, leftover disk detection, recovery failure handling and ownership checks. Python and shell syntax checks passed.'),
        para('Measured dependency versions: '+escape(', '.join(k+' '+v for k,v in metrics['versions'].items())),'SmallHW'),
        para('Full per-class reports, confusion matrices, partition membership and hashes are saved in metrics.json, splits.csv and migration.json. '+('Cloud cleanup has been verified.' if cloud else '<b>Cloud migration and cleanup evidence remain pending.</b>')),
        sub('Sources'),para('1. CS528-HW_6.pdf, assignment instructions supplied by the instructor.<br/>2. Cloud Computing (lecture 13) -- Database optimization.pdf, normal forms, slides 5, 7, 9 and 11.<br/>3. HW5 source schema and formal-run backup in CS528-HW5.<br/>4. <link href="https://scikit-learn.org/1.7/modules/ensemble.html" color="#087E8B">scikit-learn ensemble documentation</link>.<br/>5. <link href="https://docs.cloud.google.com/compute/docs/instances/startup-scripts/linux" color="#087E8B">Google Compute Engine Linux startup scripts</link>.','SmallHW')]

    def decorate(canvas,doc):
        canvas.saveState();canvas.setStrokeColor(TEAL);canvas.setLineWidth(.7)
        canvas.line(45,755,567,755);canvas.setFillColor(BLUE);canvas.setFont('Helvetica',8)
        canvas.drawString(45,765,'CS528 | Homework 6 | Yide Fang')
        canvas.setFont('Helvetica',7);canvas.drawString(45,28,status)
        canvas.drawRightString(567,28,str(doc.page));canvas.restoreState()
    doc=SimpleDocTemplate(str(output),pagesize=(612,792),leftMargin=45,rightMargin=45,topMargin=52,bottomMargin=48,
                          title='CS528 Homework 6 - Yide Fang',author='Yide Fang')
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    print(output)


if __name__=='__main__': main()
