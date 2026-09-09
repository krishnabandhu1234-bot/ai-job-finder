"""Curated keyword lists used by the resume extractor to recognize
explicit mentions of skills, tools, and credentials in resume text.

This is NOT the job-matching engine (that comes in Phase 4 and explicitly
avoids naive keyword matching per the project spec) - this is resume
*extraction*: turning unstructured resume text into a structured list of
things the candidate actually wrote on their resume. Recognizing "Python"
or "PMP" as a known term is standard practice for every resume parser and
is a different problem from judging whether a candidate is a good fit for
a job.

Lists are intentionally curated rather than exhaustive - they cover common
terms across software/hardware/simulation/data engineering disciplines
(reflecting the kinds of roles used as examples throughout the project
spec, e.g. thermal/CFD/simulation engineering alongside ML/software) and
can grow over time without touching extractor.py.
"""

from __future__ import annotations

PROGRAMMING_LANGUAGES = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Golang",
    "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Scala", "R", "MATLAB", "Julia",
    "Perl", "Objective-C", "SQL", "Bash", "Shell Scripting", "PowerShell",
    "Fortran", "VBA", "Dart", "Lua", "Haskell", "COBOL", "Assembly", "Groovy",
    "C", "Visual Basic",
]

SOFTWARE_TOOLS = [
    "ANSYS", "SolidWorks", "AutoCAD", "CATIA", "Simulink", "LabVIEW",
    "COMSOL", "Fluent", "OpenFOAM", "Abaqus", "Siemens NX", "PTC Creo",
    "Excel", "PowerPoint", "Microsoft Word", "Jira", "Confluence", "Git",
    "GitHub", "GitLab", "Bitbucket", "Docker", "Kubernetes", "Jenkins",
    "Terraform", "Ansible", "Chef", "Puppet", "Salesforce", "SAP", "Tableau",
    "Power BI", "Looker", "Photoshop", "Illustrator", "Figma", "Sketch",
    "Blender", "Unity", "Unreal Engine", "Revit", "MapInfo", "ArcGIS",
    "Minitab", "JMP", "Bloomberg Terminal", "SPSS", "Stata",
]

FRAMEWORKS_LIBRARIES = [
    "React", "Angular", "Vue.js", "Django", "Flask", "FastAPI", "Spring",
    "Spring Boot", ".NET", "Node.js", "Express.js", "TensorFlow", "PyTorch",
    "Keras", "scikit-learn", "pandas", "NumPy", "SciPy", "OpenCV", "Hadoop",
    "Apache Spark", "Kafka", "Airflow", "GraphQL", "REST", "gRPC", "Next.js",
    "Svelte", "jQuery", "Bootstrap", "Tailwind CSS", "Hugging Face",
    "LangChain", "XGBoost", "LightGBM",
]

DATABASES = [
    "MySQL", "PostgreSQL", "MongoDB", "SQLite", "Oracle Database",
    "SQL Server", "Redis", "Cassandra", "DynamoDB", "Elasticsearch",
    "Snowflake", "BigQuery", "Redshift", "Neo4j", "MariaDB", "Firebase",
]

CLOUD_PLATFORMS = [
    "AWS", "Amazon Web Services", "Azure", "Microsoft Azure", "GCP",
    "Google Cloud Platform", "IBM Cloud", "Oracle Cloud", "DigitalOcean",
    "Heroku",
]

CERTIFICATIONS = [
    "PMP", "PE", "Professional Engineer", "CFA", "CPA", "Six Sigma",
    "Lean Six Sigma", "AWS Certified", "Azure Certified", "CISSP", "CISM",
    "CISA", "Certified Scrum Master", "CSM", "PSM", "ITIL", "CCNA", "CCNP",
    "SHRM-CP", "PHR", "SPHR", "FE Exam", "Fundamentals of Engineering",
    "CFD Certified", "Certified Kubernetes Administrator", "CKA",
    "Google Cloud Certified", "Microsoft Certified",
]

DEGREE_KEYWORDS = [
    "Ph.D.", "PhD", "Doctorate", "Doctor of Philosophy", "MBA", "M.S.", "MS",
    "Master of Science", "Master of Engineering", "M.Eng", "MEng", "Masters",
    "M.A.", "MA", "Master of Arts", "B.S.", "BS", "Bachelor of Science",
    "B.A.", "BA", "Bachelor of Arts", "B.E.", "BE", "Bachelor of Engineering",
    "B.Tech", "BTech", "M.Tech", "MTech", "Associate Degree", "A.S.",
]

LEADERSHIP_PHRASES = [
    "managed a team", "led a team", "led cross-functional", "team lead",
    "tech lead", "technical lead", "engineering manager", "director of",
    "vp of", "vice president of", "head of", "supervised", "mentored",
    "managed direct reports", "people manager", "line manager",
    "managed a group of", "oversaw a team", "built and led", "hired and managed",
]

LEADERSHIP_TITLE_MARKERS = [
    "manager", "director", "vp", "vice president", "head of", "chief",
    "lead", "principal", "supervisor", "team lead",
]

SECTION_HEADERS = {
    "summary": ["summary", "professional summary", "profile", "objective", "about me"],
    "experience": [
        "experience", "work experience", "professional experience",
        "employment history", "employment", "career history", "work history",
    ],
    "education": ["education", "academic background", "academic history"],
    "skills": [
        "skills", "technical skills", "core competencies", "competencies",
        "technologies", "technical proficiencies",
    ],
    "certifications": ["certifications", "licenses", "licenses and certifications", "certificates"],
    "projects": ["projects", "personal projects", "key projects", "selected projects"],
    "publications": ["publications", "papers", "research publications"],
}

ALL_SECTION_HEADER_TERMS = {term for terms in SECTION_HEADERS.values() for term in terms}
