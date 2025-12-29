# DTDP — Drug-Target-Discovery-Pipeline

## 📌 Project Overview
**DTDP (Drug Target Discovery Pipeline)**, is a comprehensive, multi-module bioinformatics platform designed to streamline the identification of novel therapeutic targets in bacterial pathogens. By integrating comparative genomics, structural biology, and mutational analysis, the pipeline filters massive proteomic datasets down to high-priority candidates that are essential to the pathogen, non-homologous to humans, and clinically relevant.

Developed for researchers in biotechnology, this pipeline bridges the gap between raw genomic data and actionable drug targets through a high-performance Python backend and an intuitive, real-time web interface.

---

## 🚀 Why Use DTDP?
Identifying a viable drug target is a "needle in a haystack" challenge. DTDP automates the identification of critical target criteria while providing deep molecular insights:

* **Essentiality & Selectivity:** Filters targets to ensure they are essential for bacterial survival while remaining non-homologous to human proteins to minimize side effects.
* **Sequence Variation Analysis:** Utilizes Multiple Sequence Alignment (MSA) to identify critical changes and conservation patterns in protein sequences across different bacterial strains.

* **Comprehensive Structural Discovery:** Systematically searches **PDB** and **UniProt** to identify existing experimental structures.
    * **AI-Driven Prediction:** If experimental structures are unavailable, the pipeline facilitates high-accuracy structure prediction using state-of-the-art models such as **AlphaFold**, **ESMFold**, and **Boltz-2**.
* **Pathogenicity:** Prioritizes proteins involved in virulence and infection processes.
* **Conservation:** Ensures targets are conserved across multiple strains to support broad-spectrum efficacy.

---

## 💻 Technical Stack
* **Backend:** Python
* **Frontend:** Java based Local Webapp
* **OS Support:** Currently Optimized for Ubuntu 22.04 LTS or higher

---

## 📈 Key Features
* **Real-time Monitoring:** Track progress and system resources.
* **Smart Caching:** Utilizes result caching to avoid redundant runs.
* **Project Isolation:** Dedicated project directories for different research projects.
* **Interactive MSA Viewer:** Custom web viewer with color-coded amino acids and secondary structure overlay.

---

## 🎯 Conclusion
DTDP is more than a script; it is a laboratory workhorse. By combining the speed of computational biology with user-centric design, it allows researchers to focus on the **science of the target** rather than the **drudgery of data management**.
