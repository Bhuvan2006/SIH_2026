"""
Expands the curated drug-knowledge and price datasets.

Run once:  python scripts/expand_drug_data.py

WHY THIS IS CURATED RATHER THAN SCRAPED
---------------------------------------
The obvious source for Indian medicine prices is an e-pharmacy listing
(1mg / PharmEasy / Netmeds). We deliberately do not scrape those:

  * Their terms of service prohibit automated extraction, and the build plan
    (§0.2) already flags that India's e-pharmacy rules are an unsettled legal
    area -- scraping a seller's catalogue to power a "compare and switch"
    feature sits badly inside that.
  * Scraped listing prices are retail snapshots that drift daily, so a stale
    scrape shows a patient a price their pharmacist will not honour.

The authoritative Indian source is the NPPA (National Pharmaceutical Pricing
Authority), which fixes legally-binding CEILING prices for scheduled
formulations under DPCO 2013. NPPA publishes those as individual gazette PDFs
rather than a structured feed, so there is no honest "scrape it live" path --
see scripts/import_nppa_prices.py for the importer that ingests an NPPA
ceiling-price CSV once you have one.

Until then this file holds an illustrative, clearly-labelled dataset covering
the medicines most commonly dispensed in India, so the feature is exercisable
end-to-end. Clinical fields are limited to well-established, label-level facts.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "data"
CITATION = (
    "WHO Model List of Essential Medicines / standard pharmacology reference "
    "(sample data — verify against current labeling before clinical use)"
)

# --- New drug knowledge entries -------------------------------------------
NEW_DRUGS = [
    {
        "generic_name": "Montelukast", "brand_names": ["Montair", "Montek", "Telekast"],
        "composition": "Montelukast Sodium", "strength": "4mg / 5mg / 10mg",
        "drug_class": "Leukotriene receptor antagonist", "route": "oral",
        "storage_instructions": "Store below 25°C, protect from moisture and light. Usually taken in the evening.",
        "common_interactions": ["Phenobarbital and rifampicin may reduce its levels"],
        "contraindications": ["Known hypersensitivity to montelukast"],
        "conditions_treated": ["asthma", "allergy"],
    },
    {
        "generic_name": "Amoxicillin + Clavulanic Acid", "brand_names": ["Augmentin", "Clavam", "Moxikind-CV"],
        "composition": "Amoxicillin + Clavulanic Acid", "strength": "625mg / 1g",
        "drug_class": "Penicillin antibiotic with beta-lactamase inhibitor", "route": "oral",
        "storage_instructions": "Store below 25°C in a dry place. Reconstituted syrup must be refrigerated and discarded after the period on the label. Take with food to reduce stomach upset.",
        "common_interactions": ["May reduce effectiveness of some hormonal contraceptives", "Increased bleeding risk with warfarin"],
        "contraindications": ["Known penicillin allergy", "Previous jaundice with this combination"],
        "conditions_treated": ["bacterial_infection"],
    },
    {
        "generic_name": "Cefixime", "brand_names": ["Taxim-O", "Zifi", "Mahacef"],
        "composition": "Cefixime Trihydrate", "strength": "100mg / 200mg",
        "drug_class": "Cephalosporin antibiotic", "route": "oral",
        "storage_instructions": "Store below 25°C, protect from moisture. Complete the full course.",
        "common_interactions": ["Increased bleeding risk with anticoagulants"],
        "contraindications": ["Known cephalosporin hypersensitivity", "Caution with severe penicillin allergy"],
        "conditions_treated": ["bacterial_infection"],
    },
    {
        "generic_name": "Ciprofloxacin", "brand_names": ["Ciplox", "Cifran"],
        "composition": "Ciprofloxacin Hydrochloride", "strength": "250mg / 500mg",
        "drug_class": "Fluoroquinolone antibiotic", "route": "oral",
        "storage_instructions": "Store below 25°C. Take with plenty of water. Avoid dairy, antacids, iron and calcium within 2 hours of the dose.",
        "common_interactions": ["Absorption reduced by dairy, antacids, iron, calcium", "Increased tendon-injury risk with corticosteroids", "Raises theophylline levels"],
        "contraindications": ["History of tendon disorders with quinolones", "Pregnancy and children (growth-plate caution)"],
        "conditions_treated": ["bacterial_infection"],
    },
    {
        "generic_name": "Ondansetron", "brand_names": ["Emeset", "Vomikind", "Zofer"],
        "composition": "Ondansetron Hydrochloride", "strength": "4mg / 8mg",
        "drug_class": "Antiemetic (5-HT3 antagonist)", "route": "oral / injection",
        "storage_instructions": "Store below 30°C, protect from light.",
        "common_interactions": ["Can prolong QT interval with other QT-prolonging drugs", "Serotonin syndrome risk with certain antidepressants"],
        "contraindications": ["Congenital long QT syndrome", "Concurrent apomorphine"],
        "conditions_treated": ["nausea_vomiting"],
    },
    {
        "generic_name": "Rabeprazole", "brand_names": ["Razo", "Rabium", "Happi"],
        "composition": "Rabeprazole Sodium", "strength": "10mg / 20mg",
        "drug_class": "Proton pump inhibitor", "route": "oral",
        "storage_instructions": "Store below 25°C, protect from moisture. Take 30-60 minutes before a meal, swallowed whole.",
        "common_interactions": ["Reduces absorption of drugs needing stomach acid", "May affect clopidogrel activation"],
        "contraindications": ["Known hypersensitivity to PPIs"],
        "conditions_treated": ["acid_reflux", "peptic_ulcer"],
    },
    {
        "generic_name": "Telmisartan", "brand_names": ["Telma", "Telmikind", "Telsar"],
        "composition": "Telmisartan", "strength": "20mg / 40mg / 80mg",
        "drug_class": "Angiotensin receptor blocker (ARB, antihypertensive)", "route": "oral",
        "storage_instructions": "Store below 30°C in the original blister, protect from moisture.",
        "common_interactions": ["Raised potassium with potassium-sparing diuretics or supplements", "NSAIDs may reduce effect and affect kidney function", "Increases lithium levels"],
        "contraindications": ["Pregnancy (all trimesters)", "Bilateral renal artery stenosis", "Severe liver impairment"],
        "conditions_treated": ["hypertension"],
    },
    {
        "generic_name": "Metoprolol", "brand_names": ["Metolar", "Betaloc", "Metpure"],
        "composition": "Metoprolol Succinate / Tartrate", "strength": "25mg / 50mg / 100mg",
        "drug_class": "Beta-blocker (cardioselective)", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from light and moisture. Do not stop suddenly — abrupt withdrawal can worsen angina.",
        "common_interactions": ["Masks warning signs of low blood sugar in diabetes", "Additive effect with other blood-pressure medicines", "Verapamil/diltiazem increase risk of slow heart rate"],
        "contraindications": ["Severe bradycardia or heart block", "Decompensated heart failure", "Severe asthma (caution)"],
        "conditions_treated": ["hypertension", "cardiovascular_prevention"],
    },
    {
        "generic_name": "Rosuvastatin", "brand_names": ["Rosuvas", "Crestor", "Rozavel"],
        "composition": "Rosuvastatin Calcium", "strength": "5mg / 10mg / 20mg",
        "drug_class": "Statin (lipid-lowering)", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from moisture and light. Can be taken at any time of day, consistently.",
        "common_interactions": ["Increased muscle-toxicity risk with certain antibiotics/antifungals and fibrates", "Antacids reduce absorption — separate by 2 hours"],
        "contraindications": ["Active liver disease", "Pregnancy and breastfeeding", "Unexplained persistent muscle pain"],
        "conditions_treated": ["dyslipidemia"],
    },
    {
        "generic_name": "Glimepiride", "brand_names": ["Amaryl", "Glimestar", "Zoryl"],
        "composition": "Glimepiride", "strength": "1mg / 2mg / 4mg",
        "drug_class": "Sulfonylurea (oral antidiabetic)", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from moisture. Take with or just before breakfast — do not skip the meal after taking it.",
        "common_interactions": ["Hypoglycaemia risk raised by alcohol and other antidiabetics", "Beta-blockers can mask low-blood-sugar symptoms"],
        "contraindications": ["Type 1 diabetes", "Diabetic ketoacidosis", "Severe kidney or liver impairment"],
        "conditions_treated": ["diabetes_type_2"],
    },
    {
        "generic_name": "Sitagliptin", "brand_names": ["Januvia", "Istavel", "Sitazit"],
        "composition": "Sitagliptin Phosphate", "strength": "25mg / 50mg / 100mg",
        "drug_class": "DPP-4 inhibitor (oral antidiabetic)", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from moisture.",
        "common_interactions": ["Hypoglycaemia risk increases when combined with sulfonylureas or insulin"],
        "contraindications": ["Type 1 diabetes", "History of pancreatitis (caution)", "Dose reduction in kidney impairment"],
        "conditions_treated": ["diabetes_type_2"],
    },
    {
        "generic_name": "Levocetirizine", "brand_names": ["Levocet", "Xyzal", "1-Al"],
        "composition": "Levocetirizine Dihydrochloride", "strength": "5mg",
        "drug_class": "Antihistamine", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from moisture. Usually taken in the evening as it can cause drowsiness.",
        "common_interactions": ["Additive drowsiness with alcohol or sedatives"],
        "contraindications": ["Severe kidney impairment", "Known hypersensitivity"],
        "conditions_treated": ["allergy"],
    },
    {
        "generic_name": "Prednisolone", "brand_names": ["Omnacortil", "Wysolone"],
        "composition": "Prednisolone", "strength": "5mg / 10mg / 20mg / 40mg",
        "drug_class": "Corticosteroid", "route": "oral",
        "storage_instructions": "Store below 25°C. Take with food in the morning. Never stop a longer course abruptly — the dose must be tapered.",
        "common_interactions": ["Increased stomach-ulcer risk with NSAIDs", "Raises blood sugar — diabetes doses may need adjusting", "Live vaccines should be avoided"],
        "contraindications": ["Systemic fungal infection", "Live vaccine administration"],
        "conditions_treated": ["inflammation", "asthma", "autoimmune"],
    },
    {
        "generic_name": "Ramipril", "brand_names": ["Cardace", "Ramistar"],
        "composition": "Ramipril", "strength": "1.25mg / 2.5mg / 5mg / 10mg",
        "drug_class": "ACE inhibitor (antihypertensive)", "route": "oral",
        "storage_instructions": "Store below 25°C, protect from moisture.",
        "common_interactions": ["Raised potassium with potassium supplements/sparing diuretics", "NSAIDs reduce effect and may affect kidneys", "Increases lithium levels"],
        "contraindications": ["Pregnancy (all trimesters)", "History of angioedema", "Bilateral renal artery stenosis"],
        "conditions_treated": ["hypertension"],
    },
    {
        "generic_name": "Furosemide", "brand_names": ["Lasix", "Frusenex"],
        "composition": "Furosemide", "strength": "20mg / 40mg",
        "drug_class": "Loop diuretic", "route": "oral / injection",
        "storage_instructions": "Store below 25°C, protect from light. Take in the morning to avoid night-time urination.",
        "common_interactions": ["Can lower potassium and sodium", "Increased ototoxicity with certain antibiotics", "NSAIDs reduce effectiveness"],
        "contraindications": ["Anuria (no urine output)", "Severe electrolyte depletion"],
        "conditions_treated": ["heart_failure", "hypertension", "oedema"],
    },
    {
        "generic_name": "Pregabalin", "brand_names": ["Lyrica", "Pregeb", "Maxgalin"],
        "composition": "Pregabalin", "strength": "50mg / 75mg / 150mg",
        "drug_class": "Anticonvulsant / neuropathic pain agent", "route": "oral",
        "storage_instructions": "Store below 25°C. Do not stop suddenly — taper under medical advice.",
        "common_interactions": ["Additive drowsiness with alcohol, opioids and sedatives — respiratory depression risk"],
        "contraindications": ["Known hypersensitivity", "Dose reduction needed in kidney impairment"],
        "conditions_treated": ["neuropathic_pain", "epilepsy"],
    },
    {
        "generic_name": "Escitalopram", "brand_names": ["Nexito", "Cipralex", "Feliz-S"],
        "composition": "Escitalopram Oxalate", "strength": "5mg / 10mg / 20mg",
        "drug_class": "SSRI antidepressant", "route": "oral",
        "storage_instructions": "Store below 25°C, protect from moisture. Do not stop abruptly — withdrawal symptoms are common; taper with your doctor.",
        "common_interactions": ["Serotonin syndrome risk with other serotonergic drugs including tramadol", "Increased bleeding risk with NSAIDs/anticoagulants", "Can prolong QT interval"],
        "contraindications": ["Concurrent MAO inhibitors", "Congenital long QT syndrome"],
        "conditions_treated": ["depression", "anxiety"],
    },
    {
        "generic_name": "Fluconazole", "brand_names": ["Forcan", "Zocon", "Fluka"],
        "composition": "Fluconazole", "strength": "50mg / 150mg / 200mg",
        "drug_class": "Antifungal (triazole)", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from moisture.",
        "common_interactions": ["Raises levels of warfarin, phenytoin and some statins", "Can prolong QT interval"],
        "contraindications": ["Concurrent cisapride or terfenadine", "Pregnancy at high doses"],
        "conditions_treated": ["fungal_infection"],
    },
    {
        "generic_name": "Albendazole", "brand_names": ["Zentel", "Bandy"],
        "composition": "Albendazole", "strength": "400mg",
        "drug_class": "Antihelminthic", "route": "oral",
        "storage_instructions": "Store below 30°C. Take with a fatty meal to improve absorption. Chew tablets before swallowing.",
        "common_interactions": ["Levels increased by dexamethasone and cimetidine"],
        "contraindications": ["Pregnancy", "Known hypersensitivity"],
        "conditions_treated": ["parasitic_infection"],
    },
    {
        "generic_name": "Cholecalciferol (Vitamin D3)", "brand_names": ["Uprise-D3", "Calcirol", "D-Rise"],
        "composition": "Cholecalciferol", "strength": "1000 IU / 60000 IU",
        "drug_class": "Vitamin supplement", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from light. High-dose (60000 IU) sachets are usually weekly, not daily — check the prescribed interval carefully.",
        "common_interactions": ["Thiazide diuretics can raise calcium levels", "Reduced absorption with orlistat and cholestyramine"],
        "contraindications": ["High blood calcium", "Kidney stones (caution)"],
        "conditions_treated": ["vitamin_d_deficiency"],
    },
    {
        "generic_name": "Ferrous Sulphate + Folic Acid", "brand_names": ["Livogen", "Fefol", "Autrin"],
        "composition": "Ferrous Sulphate + Folic Acid", "strength": "Varies by product",
        "drug_class": "Haematinic (iron supplement)", "route": "oral",
        "storage_instructions": "Store below 30°C, keep tightly closed and away from children — iron overdose in children is dangerous. Take on an empty stomach if tolerated; vitamin C aids absorption.",
        "common_interactions": ["Reduces absorption of levothyroxine, tetracyclines and quinolones — separate by 2-4 hours", "Tea, coffee and calcium reduce iron absorption"],
        "contraindications": ["Iron-overload disorders (haemochromatosis)", "Anaemia not caused by iron deficiency"],
        "conditions_treated": ["anaemia"],
    },
    {
        "generic_name": "Calcium Carbonate + Vitamin D3", "brand_names": ["Shelcal", "Calcimax", "Gemcal"],
        "composition": "Calcium Carbonate + Cholecalciferol", "strength": "500mg + 250 IU",
        "drug_class": "Mineral / vitamin supplement", "route": "oral",
        "storage_instructions": "Store below 30°C, protect from moisture. Take with food for better absorption.",
        "common_interactions": ["Reduces absorption of levothyroxine, iron, tetracyclines and quinolones — separate by at least 2-4 hours"],
        "contraindications": ["High blood calcium", "Severe kidney impairment (caution)"],
        "conditions_treated": ["calcium_deficiency", "osteoporosis"],
    },
]

# --- Price entries, keyed by generic_name ---------------------------------
# Branded vs. generic/Jan-Aushadhi spread is illustrative of the real pattern
# (generics typically a fraction of branded price) but is NOT live pricing.
NEW_PRICES = {
    "Montelukast": [
        {"product_name": "Montair 10", "manufacturer": "Cipla", "is_generic": False, "price_inr": 195.0, "unit": "strip of 15 tablets"},
        {"product_name": "Montelukast 10mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 42.0, "unit": "strip of 15 tablets"},
    ],
    "Amoxicillin + Clavulanic Acid": [
        {"product_name": "Augmentin 625 Duo", "manufacturer": "GSK", "is_generic": False, "price_inr": 205.0, "unit": "strip of 10 tablets"},
        {"product_name": "Clavam 625", "manufacturer": "Alkem", "is_generic": False, "price_inr": 178.0, "unit": "strip of 10 tablets"},
        {"product_name": "Amoxicillin+Clavulanate 625mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 68.0, "unit": "strip of 10 tablets"},
    ],
    "Cefixime": [
        {"product_name": "Zifi 200", "manufacturer": "FDC", "is_generic": False, "price_inr": 122.0, "unit": "strip of 10 tablets"},
        {"product_name": "Cefixime 200mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 38.0, "unit": "strip of 10 tablets"},
    ],
    "Ciprofloxacin": [
        {"product_name": "Ciplox 500", "manufacturer": "Cipla", "is_generic": False, "price_inr": 62.0, "unit": "strip of 10 tablets"},
        {"product_name": "Ciprofloxacin 500mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 17.0, "unit": "strip of 10 tablets"},
    ],
    "Ondansetron": [
        {"product_name": "Emeset 4", "manufacturer": "Cipla", "is_generic": False, "price_inr": 38.0, "unit": "strip of 10 tablets"},
        {"product_name": "Ondansetron 4mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 11.0, "unit": "strip of 10 tablets"},
    ],
    "Rabeprazole": [
        {"product_name": "Razo 20", "manufacturer": "Dr. Reddy's", "is_generic": False, "price_inr": 132.0, "unit": "strip of 15 tablets"},
        {"product_name": "Rabeprazole 20mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 29.0, "unit": "strip of 15 tablets"},
    ],
    "Telmisartan": [
        {"product_name": "Telma 40", "manufacturer": "Glenmark", "is_generic": False, "price_inr": 118.0, "unit": "strip of 15 tablets"},
        {"product_name": "Telmisartan 40mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 26.0, "unit": "strip of 15 tablets"},
    ],
    "Metoprolol": [
        {"product_name": "Metolar XR 50", "manufacturer": "Cipla", "is_generic": False, "price_inr": 96.0, "unit": "strip of 15 tablets"},
        {"product_name": "Metoprolol 50mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 24.0, "unit": "strip of 15 tablets"},
    ],
    "Rosuvastatin": [
        {"product_name": "Rosuvas 10", "manufacturer": "Sun Pharma", "is_generic": False, "price_inr": 168.0, "unit": "strip of 15 tablets"},
        {"product_name": "Rosuvastatin 10mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 41.0, "unit": "strip of 15 tablets"},
    ],
    "Glimepiride": [
        {"product_name": "Amaryl 2", "manufacturer": "Sanofi", "is_generic": False, "price_inr": 142.0, "unit": "strip of 15 tablets"},
        {"product_name": "Glimepiride 2mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 27.0, "unit": "strip of 15 tablets"},
    ],
    "Sitagliptin": [
        {"product_name": "Januvia 100", "manufacturer": "MSD", "is_generic": False, "price_inr": 385.0, "unit": "strip of 7 tablets"},
        {"product_name": "Sitagliptin 100mg (generic)", "manufacturer": "Various", "is_generic": True, "price_inr": 96.0, "unit": "strip of 10 tablets"},
    ],
    "Levocetirizine": [
        {"product_name": "Xyzal 5", "manufacturer": "UCB", "is_generic": False, "price_inr": 88.0, "unit": "strip of 10 tablets"},
        {"product_name": "Levocetirizine 5mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 13.0, "unit": "strip of 10 tablets"},
    ],
    "Prednisolone": [
        {"product_name": "Omnacortil 10", "manufacturer": "Macleods", "is_generic": False, "price_inr": 42.0, "unit": "strip of 10 tablets"},
        {"product_name": "Prednisolone 10mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 12.0, "unit": "strip of 10 tablets"},
    ],
    "Ramipril": [
        {"product_name": "Cardace 5", "manufacturer": "Sanofi", "is_generic": False, "price_inr": 128.0, "unit": "strip of 15 tablets"},
        {"product_name": "Ramipril 5mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 30.0, "unit": "strip of 15 tablets"},
    ],
    "Furosemide": [
        {"product_name": "Lasix 40", "manufacturer": "Sanofi", "is_generic": False, "price_inr": 38.0, "unit": "strip of 15 tablets"},
        {"product_name": "Furosemide 40mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 9.5, "unit": "strip of 15 tablets"},
    ],
    "Pregabalin": [
        {"product_name": "Lyrica 75", "manufacturer": "Pfizer", "is_generic": False, "price_inr": 445.0, "unit": "strip of 14 capsules"},
        {"product_name": "Pregabalin 75mg (generic)", "manufacturer": "Various", "is_generic": True, "price_inr": 98.0, "unit": "strip of 10 capsules"},
    ],
    "Escitalopram": [
        {"product_name": "Nexito 10", "manufacturer": "Sun Pharma", "is_generic": False, "price_inr": 132.0, "unit": "strip of 10 tablets"},
        {"product_name": "Escitalopram 10mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 31.0, "unit": "strip of 10 tablets"},
    ],
    "Fluconazole": [
        {"product_name": "Forcan 150", "manufacturer": "Cipla", "is_generic": False, "price_inr": 58.0, "unit": "single tablet"},
        {"product_name": "Fluconazole 150mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 14.0, "unit": "single tablet"},
    ],
    "Albendazole": [
        {"product_name": "Zentel 400", "manufacturer": "GSK", "is_generic": False, "price_inr": 28.0, "unit": "single tablet"},
        {"product_name": "Albendazole 400mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 7.0, "unit": "single tablet"},
    ],
    "Cholecalciferol (Vitamin D3)": [
        {"product_name": "Uprise-D3 60K", "manufacturer": "Alkem", "is_generic": False, "price_inr": 92.0, "unit": "pack of 4 sachets"},
        {"product_name": "Cholecalciferol 60000 IU (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 25.0, "unit": "pack of 4 sachets"},
    ],
    "Ferrous Sulphate + Folic Acid": [
        {"product_name": "Livogen", "manufacturer": "Merck", "is_generic": False, "price_inr": 46.0, "unit": "strip of 10 tablets"},
        {"product_name": "Ferrous Sulphate + Folic Acid (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 8.0, "unit": "strip of 10 tablets"},
    ],
    "Calcium Carbonate + Vitamin D3": [
        {"product_name": "Shelcal 500", "manufacturer": "Torrent", "is_generic": False, "price_inr": 118.0, "unit": "strip of 15 tablets"},
        {"product_name": "Calcium + Vitamin D3 (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 28.0, "unit": "strip of 15 tablets"},
    ],
    # --- Fill the gap: existing drugs that had NO price entries at all ---
    "Doxycycline": [
        {"product_name": "Doxy-1 L-DR", "manufacturer": "USV", "is_generic": False, "price_inr": 68.0, "unit": "strip of 10 capsules"},
        {"product_name": "Doxycycline 100mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 16.0, "unit": "strip of 10 capsules"},
    ],
    "Levothyroxine": [
        {"product_name": "Thyronorm 50mcg", "manufacturer": "Abbott", "is_generic": False, "price_inr": 148.0, "unit": "bottle of 120 tablets"},
        {"product_name": "Levothyroxine 50mcg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 42.0, "unit": "bottle of 100 tablets"},
    ],
    "Salbutamol": [
        {"product_name": "Asthalin HFA Inhaler", "manufacturer": "Cipla", "is_generic": False, "price_inr": 128.0, "unit": "200-dose inhaler"},
        {"product_name": "Salbutamol Inhaler (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 62.0, "unit": "200-dose inhaler"},
    ],
    "Clopidogrel": [
        {"product_name": "Clopilet 75", "manufacturer": "Sun Pharma", "is_generic": False, "price_inr": 112.0, "unit": "strip of 15 tablets"},
        {"product_name": "Clopidogrel 75mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 26.0, "unit": "strip of 15 tablets"},
    ],
    "Warfarin": [
        {"product_name": "Warf 5", "manufacturer": "Cipla", "is_generic": False, "price_inr": 58.0, "unit": "strip of 30 tablets"},
        {"product_name": "Warfarin 5mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 19.0, "unit": "strip of 30 tablets"},
    ],
    "Diclofenac": [
        {"product_name": "Voveran SR 100", "manufacturer": "Novartis", "is_generic": False, "price_inr": 74.0, "unit": "strip of 10 tablets"},
        {"product_name": "Diclofenac 50mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 11.0, "unit": "strip of 10 tablets"},
    ],
    "Metronidazole": [
        {"product_name": "Flagyl 400", "manufacturer": "Abbott", "is_generic": False, "price_inr": 52.0, "unit": "strip of 15 tablets"},
        {"product_name": "Metronidazole 400mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 13.0, "unit": "strip of 15 tablets"},
    ],
    "Oral Rehydration Salts (ORS)": [
        {"product_name": "Electral Powder", "manufacturer": "FDC", "is_generic": False, "price_inr": 22.0, "unit": "21.8g sachet"},
        {"product_name": "ORS WHO formula (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 8.0, "unit": "21.8g sachet"},
    ],
    "Insulin (Regular/Soluble)": [
        {"product_name": "Huminsulin R", "manufacturer": "Eli Lilly", "is_generic": False, "price_inr": 285.0, "unit": "10mL vial"},
        {"product_name": "Actrapid", "manufacturer": "Novo Nordisk", "is_generic": False, "price_inr": 265.0, "unit": "10mL vial"},
    ],
    "Pantoprazole": [
        {"product_name": "Pantop 40", "manufacturer": "Aristo", "is_generic": False, "price_inr": 138.0, "unit": "strip of 15 tablets"},
        {"product_name": "Pantoprazole 40mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 31.0, "unit": "strip of 15 tablets"},
    ],
    "Aspirin (low-dose)": [
        {"product_name": "Ecosprin 75", "manufacturer": "USV", "is_generic": False, "price_inr": 12.0, "unit": "strip of 14 tablets"},
        {"product_name": "Aspirin 75mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 4.5, "unit": "strip of 14 tablets"},
    ],
    "Hydrochlorothiazide": [
        {"product_name": "Aquazide 12.5", "manufacturer": "Sun Pharma", "is_generic": False, "price_inr": 44.0, "unit": "strip of 15 tablets"},
        {"product_name": "Hydrochlorothiazide 12.5mg (Jan Aushadhi)", "manufacturer": "PMBJP", "is_generic": True, "price_inr": 10.0, "unit": "strip of 15 tablets"},
    ],
}


def main() -> None:
    kb_path = DATA_DIR / "drug_knowledge.json"
    price_path = DATA_DIR / "price_data.json"

    drugs = json.loads(kb_path.read_text(encoding="utf-8"))
    existing = {d["generic_name"] for d in drugs}

    added = 0
    for entry in NEW_DRUGS:
        if entry["generic_name"] in existing:
            continue
        entry = {**entry, "source_citation": CITATION}
        drugs.append(entry)
        added += 1

    kb_path.write_text(json.dumps(drugs, indent=2, ensure_ascii=False), encoding="utf-8")

    prices = json.loads(price_path.read_text(encoding="utf-8"))
    entries = prices.setdefault("entries", {})
    price_added = 0
    for generic, rows in NEW_PRICES.items():
        if generic in entries:
            continue
        entries[generic] = rows
        price_added += len(rows)

    price_path.write_text(json.dumps(prices, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"drug_knowledge.json: +{added} drugs (total {len(drugs)})")
    print(f"price_data.json:     +{price_added} price rows across {len(entries)} generics")


if __name__ == "__main__":
    main()
