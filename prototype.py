"""PAIBS Group 6: reproducible Green-Score research prototype.

Commands: python prototype.py train | serve | predict --code BARCODE | test
The model imitates OFF's France-context computed score. It does not measure impact.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import gzip
import html
import json
import math
import pickle
import re
import sys
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.metrics import mean_absolute_error, f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parent
SEED = 20261027
LANGS = {'en', 'fr', 'es'}
GRADES = {'a-plus', 'a+', 'a', 'b', 'c', 'd', 'e', 'f'}
EXCLUDED = {'en:waters', 'en:sodas', 'en:energy-drinks', 'en:fresh-vegetables', 'en:fresh-fruits'}


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', value or ''))).strip()


def main_text(value, language=''):
    if isinstance(value, str):
        return clean(value)
    value = value or []
    for lc in ('main', language, 'en', 'fr', 'es'):
        for item in value:
            if item.get('lang') == lc and item.get('text'):
                return clean(item['text'])
    return clean(next((x.get('text', '') for x in value if x.get('text')), ''))


def parse_details(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}


def prepare(raw):
    lang = raw.get('lang') or ''
    ingredients = main_text(raw.get('ingredients_text'), lang)
    categories = raw.get('categories_tags') or []
    details = parse_details(raw.get('environmental_score_data'))
    grade = raw.get('environmental_score_grade') or 'unknown'
    # Use the explicit France score where available. The top-level export value
    # is retained only as a documented fallback, never as an input feature.
    score = (details.get('scores') or {}).get('fr')
    target_source = 'scores.fr'
    if score is None:
        score = raw.get('environmental_score_score')
        target_source = 'export default'
    valid_number = isinstance(score, (float, int)) and not isinstance(score, bool) and math.isfinite(score)
    not_applicable = grade == 'not-applicable' or bool(EXCLUDED.intersection(categories))
    numeric_label = valid_number and grade in GRADES and not not_applicable
    input_ok = len(ingredients) >= 15 and lang in LANGS and not not_applicable
    missing = details.get('missing') or {}
    if not_applicable:
        reason = 'not applicable'
    elif numeric_label:
        reason = 'label available'
    elif not categories or missing.get('categories'):
        reason = 'missing category'
    elif details.get('missing_agribalyse_match_warning') or missing.get('agb_category'):
        reason = 'no Agribalyse match'
    else:
        reason = 'other unknown or absent score'
    return {
        'code': str(raw.get('code') or ''),
        'name': main_text(raw.get('product_name'), lang),
        'brands': raw.get('brands') or '', 'lang': lang,
        'ingredients': ingredients, 'categories': categories,
        'category_key': categories[-1] if categories else '__missing__',
        'countries': raw.get('countries_tags') or [],
        'y': float(score) if numeric_label else None,
        'target_source': target_source, 'numeric_label': bool(numeric_label),
        'input_ok': input_ok, 'not_applicable': not_applicable,
        'missing_reason': reason, 'score_input_gaps': sorted(missing),
        'source_row': raw.get('_source_row'),
    }


def feature(row, categories=True):
    # Whitelist: original ingredient text plus category tags. No score-derived
    # data, Agribalyse components, flags, barcode, brand or product name.
    tags = ' '.join(row['categories']) if categories else ''
    return 'ingredients ' + row['ingredients'] + ' categories ' + tags


def three_rule_baseline(row, fallback):
    """Simple diagnostic: three ingredient conditions, then training majority."""
    text=row['ingredients'].lower()
    if re.search(r'\b(potato|potatoes|pommes de terre)\b',text):
        return 'en:potato-crisps'
    if re.match(r'^(milk|lait|leche)\b',text):
        return 'en:milks'
    if re.search(r'\b(cocoa|cacao)\b',text):
        return 'en:dark-chocolates'
    return fallback


def model():
    return make_pipeline(
        TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2, max_features=40000, sublinear_tf=True),
        Ridge(alpha=10.0, solver='lsqr'),
    )


def groups(rows):
    # Union exact ingredient matches and exact normalized name+brand matches.
    # This reduces duplicate/variant leakage, but is not fuzzy deduplication.
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, r in enumerate(rows):
        ing = re.sub(r'\W+', ' ', r['ingredients'].lower()).strip()
        name = re.sub(r'\W+', ' ', (r['name'] + ' ' + r['brands']).lower()).strip()
        keys = [('ing', ing)] if len(ing) >= 30 else []
        if r['name'] and r['brands'] and len(name) >= 12:
            keys.append(('name_brand', name))
        for key in keys:
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    return np.array([find(i) for i in range(len(rows))])


def load_rows():
    seen, rows = set(), []
    data_path=ROOT/'data/off_sample.jsonl'
    source=data_path.read_text() if data_path.exists() else gzip.decompress((ROOT/'data/off_sample.jsonl.gz').read_bytes()).decode()
    for line in source.splitlines():
        raw = json.loads(line)
        if raw.get('code') in seen:
            continue
        seen.add(raw.get('code'))
        rows.append(prepare(raw))
    return rows


def write_csv(path, records):
    if not records:
        return
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def train():
    out = ROOT / 'results'; out.mkdir(exist_ok=True)
    rows = load_rows()
    eligible = [r for r in rows if r['numeric_label'] and r['input_ok']]
    if len(eligible) < 100:
        raise ValueError('Fewer than 100 eligible labelled records: expand the sample before training.')
    g = groups(eligible)
    train_idx, hold_idx = next(GroupShuffleSplit(n_splits=1, test_size=.35, random_state=SEED).split(eligible, groups=g))
    cal_rel, test_rel = next(GroupShuffleSplit(n_splits=1, test_size=.60, random_state=SEED+1).split(hold_idx, groups=g[hold_idx]))
    cal_idx, test_idx = hold_idx[cal_rel], hold_idx[test_rel]
    assert not (set(g[train_idx]) & set(g[test_idx]) or set(g[cal_idx]) & set(g[test_idx]) or set(g[train_idx]) & set(g[cal_idx]))
    tr, ca, te = [[eligible[i] for i in ix] for ix in (train_idx, cal_idx, test_idx)]
    ytr, yca, yte = [np.array([r['y'] for r in rs]) for rs in (tr, ca, te)]
    combined, text_only = model(), model()
    combined.fit([feature(r) for r in tr], ytr)
    text_only.fit([feature(r, False) for r in tr], ytr)
    category_values = defaultdict(list)
    for r in tr:

        for tag in r['categories']:
            category_values[tag].append(r['y'])
    medians = {k: float(np.median(v)) for k, v in category_values.items() if len(v) >= 3}
    global_median = float(np.median(ytr))
    pglobal = np.full(len(te), global_median)
    pcat = np.array([next((medians[tag] for tag in reversed(r['categories']) if tag in medians), global_median) for r in te])
    pred = combined.predict([feature(r) for r in te])
    ptext = text_only.predict([feature(r, False) for r in te])
    pmasked = combined.predict([feature(r, False) for r in te])
    residuals = np.sort(np.abs(yca - combined.predict([feature(r) for r in ca])))
    q_index = min(len(residuals)-1, math.ceil((len(residuals)+1)*.90)-1)
    radius = float(residuals[q_index])
    # This marginal split-conformal interval relies on exchangeability. It is
    # reported for the labelled holdout only, not promised for missing labels.
    mae = lambda p: float(mean_absolute_error(yte, p))
    baseline_mae = mae(pcat)
    results = {
        'seed': SEED, 'scope': 'Main languages en/fr/es, ingredient text >=15 characters, score applicable; France-context target; category input optional',
        'sample_records': len(rows), 'numeric_label_records': sum(r['numeric_label'] for r in rows),
        'eligible_labelled': len(eligible), 'labelled_other_scope': sum(r['numeric_label'] and not r['input_ok'] for r in rows),
        'missing_score_by_reason': dict(Counter(r['missing_reason'] for r in rows if not r['numeric_label'])),
        'label_input_coverage': {k: {'labelled': sum(bool(r[k]) for r in rows if r['numeric_label']), 'unlabelled_applicable': sum(bool(r[k]) for r in rows if not r['numeric_label'] and not r['not_applicable'])} for k in ['ingredients','categories']},
        'unlabelled_applicable': sum(not r['numeric_label'] and not r['not_applicable'] for r in rows),
        'eligible_unlabelled': sum(not r['numeric_label'] and r['input_ok'] for r in rows),
        'language_counts': dict(Counter(r['lang'] for r in rows)),
        'target_sources': dict(Counter(r['target_source'] for r in eligible)),
        'target_range': [float(min(r['y'] for r in eligible)),float(max(r['y'] for r in eligible))],
        'zero_labels': sum(r['y']==0 for r in eligible),
        'train_n': len(tr), 'calibration_n': len(ca), 'test_n': len(te), 'duplicate_groups': len(set(g)),
        'test_seen_category_n': sum(r['category_key'] in medians for r in te),
        'global_median_mae': mae(pglobal), 'category_median_mae': baseline_mae,
        'combined_model_mae': mae(pred), 'ingredient_only_mae': mae(ptext),
        'combined_categories_masked_mae': mae(pmasked),
        'relative_improvement_vs_category': (baseline_mae-mae(pred))/baseline_mae,
        'interval_nominal_coverage': .90, 'interval_radius_points': radius,
        'interval_test_coverage': float(np.mean(np.abs(yte-pred)<=radius)),
        'test_median_absolute_error': float(np.median(np.abs(yte-pred))),
        'test_p90_absolute_error': float(np.quantile(np.abs(yte-pred),.90)),
        'warning': 'Labelled-sample error is not evidence of accuracy on genuinely unlabelled products; intervals may fail under distribution shift. No manual review precision has been measured.',
    }
    subgroup = []
    for key in ['lang','category_key']:
        for value in sorted(set(r[key] for r in te)):
            inds = [i for i,r in enumerate(te) if r[key]==value]
            if len(inds)>=10:
                subgroup.append({'field':key,'value':value,'n':len(inds),'model_mae':mae_subset(yte,pred,inds),'category_baseline_mae':mae_subset(yte,pcat,inds)})
    # Countries are markets where sold, not ingredient origins or score context.
    for country in sorted(set(c for r in te for c in r['countries'])):
        inds=[i for i,r in enumerate(te) if country in r['countries']]
        if len(inds)>=20:
            subgroup.append({'field':'sold_in','value':country,'n':len(inds),'model_mae':mae_subset(yte,pred,inds),'category_baseline_mae':mae_subset(yte,pcat,inds)})
    # Refined task: infer a supported recorded category from ingredient text.
    # Category labels are never included in classifier inputs. This is a
    # separate task and evaluation, not a repair of the score test result.
    supported_categories={r['category_key'] for r in rows if r['numeric_label']}
    category_rows=[r for r in rows if r['input_ok'] and r['categories'] and r['category_key'] in supported_categories]
    category_groups=groups(category_rows)
    ci_train,ci_hold=next(GroupShuffleSplit(n_splits=1,test_size=.35,random_state=SEED+10).split(category_rows,groups=category_groups))
    cc,ct=next(GroupShuffleSplit(n_splits=1,test_size=.60,random_state=SEED+11).split(ci_hold,groups=category_groups[ci_hold]))
    ci_cal,ci_test=ci_hold[cc],ci_hold[ct]
    counts=Counter(category_rows[i]['category_key'] for i in ci_train)
    allowed={k for k,n in counts.items() if n>=8}
    ctrain=[category_rows[i] for i in ci_train if category_rows[i]['category_key'] in allowed]
    ccal=[category_rows[i] for i in ci_cal if category_rows[i]['category_key'] in allowed]
    ctest=[category_rows[i] for i in ci_test if category_rows[i]['category_key'] in allowed]
    classifier=make_pipeline(TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=2,max_features=40000,sublinear_tf=True),LogisticRegression(C=4.0,max_iter=1000))
    classifier.fit([feature(r,False) for r in ctrain],[r['category_key'] for r in ctrain])
    cp=classifier.predict_proba([feature(r,False) for r in ctest]);classes=classifier.classes_
    actual=np.array([r['category_key'] for r in ctest]);best=np.argmax(cp,axis=1);predicted=classes[best]
    top3=np.argsort(cp,axis=1)[:,-3:];top3_ok=np.array([actual[i] in classes[top3[i]] for i in range(len(ctest))])
    accepted=np.max(cp,axis=1)>=.50
    majority=Counter(r['category_key'] for r in ctrain).most_common(1)[0][0]
    calp=classifier.predict_proba([feature(r,False) for r in ccal]);calbest=np.argmax(calp,axis=1);calaccept=np.max(calp,axis=1)>=.50
    caltruth=np.array([r['category_key'] for r in ccal])
    ctest_all=[category_rows[i] for i in ci_test]
    all_probs=classifier.predict_proba([feature(r,False) for r in ctest_all])
    all_truth=np.array([r['category_key'] for r in ctest_all])
    all_predictions=classes[np.argmax(all_probs,axis=1)]
    all_accepted=np.max(all_probs,axis=1)>=.50
    results.update({
        'category_class_count':len(allowed),'category_train_n':len(ctrain),'category_calibration_n':len(ccal),
        'category_test_all_n':len(ci_test),'category_test_supported_n':len(ctest),
        'category_test_supported_fraction':len(ctest)/len(ci_test),
        'category_top1_accuracy':float(np.mean(predicted==actual)),
        'category_top3_accuracy':float(np.mean(top3_ok)),
        'category_top3_accuracy_all_test':float(sum(top3_ok)/len(ci_test)),
        'category_macro_f1':float(f1_score(actual,predicted,average='macro',zero_division=0)),
        'category_majority_accuracy':float(np.mean(actual==majority)),
        'category_three_rule_accuracy_supported':float(np.mean(np.array([three_rule_baseline(r,majority) for r in ctest])==actual)),
        'category_three_rule_accuracy_all':float(np.mean(np.array([three_rule_baseline(r,majority) for r in ctest_all])==all_truth)),
        'category_accept_threshold':.50,'category_test_accepted_n':int(sum(accepted)),
        'category_test_accepted_accuracy':float(np.mean(predicted[accepted]==actual[accepted])) if sum(accepted) else None,
        'category_top1_accuracy_all_test':float(np.mean(all_predictions==all_truth)),
        'category_all_test_accepted_n':int(sum(all_accepted)),
        'category_all_test_accepted_accuracy':float(np.mean(all_predictions[all_accepted]==all_truth[all_accepted])) if sum(all_accepted) else None,
        'category_calibration_accepted_n':int(sum(calaccept)),
        'category_calibration_accepted_accuracy':float(np.mean(classes[calbest[calaccept]]==caltruth[calaccept])) if sum(calaccept) else None,
        'category_scope_note':'Category label is the last recorded category tag; classes need at least 8 training examples and occur on a numerically scored product in this sample. Reported accuracy on supported classes excludes out-of-scope true labels; all-test top3 counts those as failures. These are recorded-category labels, not verified corrections.',
        'decision':'Direct score regression failed to beat the category median. Refine the main prototype to category suggestions with contributor review; keep score regression as a documented negative experiment.',
    })
    write_csv(out/'category_splits.csv',[{'code':category_rows[i]['code'],'group':int(category_groups[i]),'split':label,'supported_class':category_rows[i]['category_key'] in allowed} for label,ix in [('train',ci_train),('calibration',ci_cal),('test',ci_test)] for i in ix])
    write_csv(out/'category_test_predictions.csv',[{'code':r['code'],'actual_category':r['category_key'],'suggested_category':str(predicted[i]),'top_class_score':float(np.max(cp[i])),'top3_correct':bool(top3_ok[i]),'accepted_at_0_5':bool(accepted[i])} for i,r in enumerate(ctest)])
    bundle={'model':combined,'ingredient_model':text_only,'category_classifier':classifier,'medians':medians,'global_median':global_median,'radius':radius,'training_categories':set(medians),'metrics':results}
    with (out/'model.pkl').open('wb') as f:pickle.dump(bundle,f)
    (out/'metrics.json').write_text(json.dumps(results,indent=2))
    write_csv(out/'subgroups.csv',subgroup)
    write_csv(out/'test_predictions.csv',[{'code':r['code'],'name':r['name'],'language':r['lang'],'category':r['category_key'],'actual':r['y'],'prediction':float(p),'category_baseline':float(b),'absolute_error':float(abs(r['y']-p)),'split':'test'} for r,p,b in zip(te,pred,pcat)])
    write_csv(out/'splits.csv',[{'code':r['code'],'group':int(g[i]),'split':label} for label,ix in [('train',train_idx),('calibration',cal_idx),('test',test_idx)] for i in ix for r in [eligible[i]]])
    queue=[review(r,bundle) for r in rows if not r['numeric_label']]
    write_csv(out/'review_queue.csv',[{k:v for k,v in r.items() if k not in ['ingredients','categories']} for r in queue])
    (out/'review_queue.json').write_text(json.dumps(queue,ensure_ascii=False,indent=2))
    (out/'metrics.txt').write_text('\n'.join(f'{k}: {v}' for k,v in results.items()))
    print(json.dumps(results,indent=2))


def mae_subset(y,p,inds):
    return float(np.mean(np.abs(y[inds]-p[inds])))


def review(row, bundle):
    result={'code':row['code'],'name':row['name'],'language':row['lang'],'missing_reason':row['missing_reason'],'ingredients':row['ingredients'],'categories':' | '.join(row['categories']),'category_candidates':'','top_class_score':'','prediction':'','reference_error_band':'','action':'','status':'abstain'}
    if row['not_applicable']:
        result['action']='Excluded: official score is not applicable to this category.'
    elif row['lang'] not in LANGS:
        result['action']='Outside initial language scope; collect or translate evidence before review.'
    elif len(row['ingredients'])<15:
        result['action']='Collect a readable ingredient list or label photo first.'
    elif 'category_classifier' in bundle:
        clf=bundle['category_classifier'];probs=clf.predict_proba([feature(row,False)])[0]
        order=np.argsort(probs)[-3:][::-1]
        result['category_candidates']=' | '.join(str(clf.classes_[i]) for i in order)
        result['top_class_score']=round(float(max(probs)),3)
        result['status']='category suggestion' if max(probs)>=.50 else 'abstain'
        result['action']='Verify category candidates against the ingredient list and label photo. Class scores are uncalibrated; rare or unseen classes may be forced into known classes. '+('Suggestion exceeds the fixed 0.50 review threshold. ' if max(probs)>=.50 else 'Below the fixed 0.50 threshold: request more evidence. ')+'No numerical Green-Score is recommended for filling; no automatic OFF writes.'
        best_category=str(clf.classes_[order[0]]).lower()
        if best_category=='en:groceries':
            result['status']='abstain'
            result['action']='Top category is too broad to establish a useful Green-Score mapping. Request a more specific category; do not add a numerical score.'
        elif best_category in {tag.lower() for tag in row['categories']}:
            result['status']='abstain'
            result['action']='Top category already exists on the record. Inspect category specificity and missing Agribalyse support instead of re-adding the same category.'
    elif row['missing_reason']=='no Agribalyse match':
        result['action']='Review category specificity and supporting Agribalyse mapping; numerical estimate withheld.'
    elif not row['categories']:
        result['action']='Review missing category; numerical estimate withheld because the combined model was evaluated with category inputs.'
    elif row['category_key'] not in bundle['training_categories']:
        result['action']='Category unseen in training; numerical estimate withheld. Review category and supporting evidence.'
    else:
        p=float(bundle['model'].predict([feature(row)])[0])
        result.update(status='experimental estimate',prediction=round(p,2),reference_error_band=round(bundle['radius'],2),action='Check the official missing-score reason and supporting product data. Estimate is a research aid, not an official score; do not write it into OFF.')
    return result


def load_bundle():
    with (ROOT/'results/model.pkl').open('rb') as f:
        return pickle.load(f)  # Load only the locally produced, trusted artifact.


def serve(port):
    bundle=load_bundle(); rows=load_rows(); bycode={r['code']:r for r in rows}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            u=urlparse(self.path)
            if u.path=='/api/metrics':
                return self.respond(json.dumps(bundle['metrics']).encode(),'application/json')
            if u.path=='/api/review':
                code=parse_qs(u.query).get('code',[''])[0]
                if code not in bycode:return self.respond(b'{"error":"barcode not in cached sample"}','application/json',404)
                return self.respond(json.dumps(review(bycode[code],bundle)).encode(),'application/json')
            code=parse_qs(u.query).get('code',[''])[0]
            cached_queue=json.loads((ROOT/'results/review_queue.json').read_text())
            codes=[r['code'] for r in cached_queue if r['status']=='category suggestion']+[r['code'] for r in cached_queue if r['status']=='abstain'][:10]
            if code in bycode and code not in codes:codes.append(code)
            queue=[bycode[c] for c in codes if c in bycode]
            choices=''.join('<option value="'+html.escape(r['code'],quote=True)+'"'+(' selected' if r['code']==code else '')+'>'+html.escape((r['name'] or r['code'])[:70]+' ('+r['code']+')')+'</option>' for r in queue)
            chosen=bycode.get(code); detail=''
            if chosen:
                data=review(chosen,bundle)
                detail='<h2>'+html.escape(chosen['name'] or code)+'</h2>'+''.join('<p><strong>'+html.escape(k.replace('_',' ').title())+':</strong> '+html.escape(str(v))+'</p>' for k,v in data.items() if k not in ['name','ingredients','prediction','reference_error_band'] and v!='')+'<p><strong>Ingredients:</strong> '+html.escape(chosen['ingredients'])+'</p>'
            metrics=bundle['metrics']
            body='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Green-Score category review prototype</title><style>body{max-width:900px;margin:40px auto;padding:0 24px;font:17px/1.6 system-ui;color:#16201b;background:#fafcfb}h1{font-size:32px}select,button{font:inherit;padding:10px;max-width:100%}button{background:#145c41;color:white;border:0}strong{font-weight:650}p{overflow-wrap:anywhere}footer{margin-top:40px;font-size:14px;color:#48534e}</style><h1>Category suggestions for Green-Score review</h1><p>Inspect category suggestions for incomplete Open Food Facts records. Check the product evidence before accepting a category. The prototype never writes to OFF and does not recommend filling numerical scores.</p>'''
            body+=f'<p>Category model: {100*metrics["category_top1_accuracy"]:.1f}% top-1 accuracy on {metrics["category_test_supported_n"]} held-out records in supported classes; class coverage {100*metrics["category_test_supported_fraction"]:.1f}%. Score regression was weaker than the category baseline ({metrics["combined_model_mae"]:.2f} vs {metrics["category_median_mae"]:.2f} MAE).</p><form><label for="code">Choose an incomplete record</label><br><select id="code" name="code">'+choices+'</select> <button>Review record</button></form>'+detail
            body+='<footer>Source: Open Food Facts, ODbL. Read-only prototype. No database writes. Category class scores are uncalibrated. Accepted-label accuracy across all test classes was 65.9%; genuine missing-category usefulness is unverified.</footer></html>'
            return self.respond(body.encode(),'text/html; charset=utf-8')
        def respond(self,data,ctype,status=200):
            self.send_response(status);self.send_header('Content-Type',ctype);self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    print(f'Open http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()


def test():
    import unittest
    class Checks(unittest.TestCase):
        def test_snapshot_integrity(self):
            manifest=json.loads((ROOT/'data/manifest.json').read_text())
            data_path=ROOT/'data/off_sample.jsonl'
            raw=data_path.read_bytes() if data_path.exists() else gzip.decompress((ROOT/'data/off_sample.jsonl.gz').read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest['sha256'])
        def test_score_range_is_preserved(self):
            for value in [-20,123]:
                r=prepare({'environmental_score_grade':'a','environmental_score_score':value})
                self.assertTrue(r['numeric_label']);self.assertEqual(r['y'],value)
        def test_zero_is_valid(self):
            r=prepare({'code':'1','lang':'en','ingredients_text':'water sugar cocoa butter','environmental_score_grade':'f','environmental_score_score':0})
            self.assertTrue(r['numeric_label']);self.assertEqual(r['y'],0)
        def test_excluded_not_missing(self):
            r=prepare({'categories_tags':['en:waters'],'environmental_score_grade':'not-applicable'})
            self.assertTrue(r['not_applicable']);self.assertEqual(r['missing_reason'],'not applicable')
        def test_multilingual_html(self):
            self.assertEqual(main_text([{'lang':'main','text':'<b>Milk</b> &amp; sugar'}]),'Milk & sugar')
        def test_duplicate_union(self):
            rs=[{'ingredients':'a sufficiently long identical ingredient list','name':'A','brands':'B'},{'ingredients':'a sufficiently long identical ingredient list','name':'C','brands':'D'}]
            self.assertEqual(groups(rs)[0],groups(rs)[1])
        def test_missing_category_abstains(self):
            r=prepare({'code':'x','lang':'en','ingredients_text':'lentils water salt and tomato'})
            self.assertEqual(review(r,{'training_categories':set()})['status'],'abstain')
        def test_saved_split_disjoint(self):
            with (ROOT/'results/splits.csv').open() as f:records=list(csv.DictReader(f))
            sets={label:{r['group'] for r in records if r['split']==label} for label in ['train','calibration','test']}
            self.assertFalse(sets['train']&sets['test'] or sets['train']&sets['calibration'] or sets['test']&sets['calibration'])
            with (ROOT/'results/category_splits.csv').open() as f:records=list(csv.DictReader(f))
            sets={label:{r['group'] for r in records if r['split']==label} for label in ['train','calibration','test']}
            self.assertFalse(sets['train']&sets['test'] or sets['train']&sets['calibration'] or sets['test']&sets['calibration'])
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['train','serve','predict','test'])
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--code',default='')
    args=parser.parse_args()
    if args.command=='train':train()
    elif args.command=='serve':serve(args.port)
    elif args.command=='test':sys.exit(test())
    else:
        row=next((r for r in load_rows() if r['code']==args.code),None)
        if row is None:parser.error('Barcode is not in the cached sample.')
        print(json.dumps(review(row,load_bundle()),indent=2,ensure_ascii=False))
