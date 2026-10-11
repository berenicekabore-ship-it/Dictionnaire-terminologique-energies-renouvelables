import io
import unicodedata

import pandas as pd
import streamlit as st

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError


# --------------------------------------------------
# 1. Configuration générale
# --------------------------------------------------

st.set_page_config(
    page_title="Dictionnaire bilingue des énergies renouvelables",
    page_icon="📚",
    layout="wide",
)

# Identifiant du document Google Drive
FILE_ID = "1CSW3D8w6SGB-eZ0vR9U-MvNzahtOojhY"

# Colonnes attendues dans la feuille terminologique
COLONNES = [
    "ID",
    "Terme français",
    "Catégorie grammaticale FR",
    "Définition française",
    "English term",
    "Part of speech EN",
    "English definition",
]


# --------------------------------------------------
# 2. Chargement sécurisé depuis Google Drive
# --------------------------------------------------

@st.cache_data(ttl=300)
def charger_donnees(file_id):
    """
    Télécharge le document depuis Google Drive en lecture seule,
    puis charge la feuille terminologique avec pandas.
    """

    # Authentification du compte de service
    credentials = service_account.Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )

    # Connexion à l'API Google Drive
    drive = build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    # Récupérer le type et le nom du document
    metadata = drive.files().get(
        fileId=file_id,
        fields="id,name,mimeType",
    ).execute()

    mime_type = metadata["mimeType"]

    # Cas 1 : document Google Sheets natif
    if mime_type == "application/vnd.google-apps.spreadsheet":
        request = drive.files().export_media(
            fileId=file_id,
            mimeType=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

    # Cas 2 : fichier Excel ou autre fichier binaire
    else:
        request = drive.files().get_media(fileId=file_id)

    # Télécharger en mémoire, sans créer de fichier local
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    termine = False

    while not termine:
        _, termine = downloader.next_chunk()

    buffer.seek(0)

    # Lire la feuille terminologique
    df = pd.read_excel(
        buffer,
        sheet_name="Glossaire bilingue",
        engine="openpyxl",
    )

    # Vérifier la structure des colonnes
    if list(df.columns) != COLONNES:
        raise ValueError(
            "Les colonnes du fichier ne correspondent pas "
            "à la structure attendue. Vérifiez les en-têtes "
            "et leur ordre dans la feuille "
            "'Glossaire bilingue'."
        )

    # Vérifier les cellules vides
    if df.isna().any().any():
        raise ValueError(
            "Des cellules sont vides. Vérifiez le classeur "
            "avant de publier le dictionnaire."
        )

    # Vérifier les identifiants en double
    if df["ID"].duplicated().any():
        raise ValueError(
            "Des identifiants sont dupliqués dans le dictionnaire."
        )

    return df, metadata["name"]


# --------------------------------------------------
# 3. Normalisation de la recherche
# --------------------------------------------------

def normaliser_recherche(texte):
    """Normalise la saisie sans modifier les données originales."""

    texte = str(texte).casefold()
    texte = unicodedata.normalize("NFKD", texte)

    return "".join(
        caractere
        for caractere in texte
        if not unicodedata.combining(caractere)
    )


# --------------------------------------------------
# 4. En-tête du dictionnaire
# --------------------------------------------------

st.title("Dictionnaire terminologique bilingue")

st.subheader(
    "Énergies renouvelables | Renewable energy"
)

st.caption(
    "Anglais – Français · Version V1 · "
    "Outil de consultation terminologique"
)


# --------------------------------------------------
# 5. Chargement de la base
# --------------------------------------------------

try:
    with st.spinner(
        "Chargement du dictionnaire depuis Google Drive..."
    ):
        donnees, nom_fichier = charger_donnees(FILE_ID)

except HttpError as erreur:
    st.error(
        "Google Drive n'a pas permis de récupérer le document. "
        "Vérifiez l'identifiant du fichier, le partage avec "
        "le compte de service et l'activation de l'API Google Drive."
    )
    st.caption(f"Détail technique : {erreur}")
    st.stop()

except Exception as erreur:
    st.error("Erreur détaillée lors du chargement de la base")
    st.exception(erreur)
    st.stop()

st.success("Le dictionnaire a été chargé avec succès.")

st.caption(
    f"Document source : {nom_fichier}"
)

st.caption(
    f"{len(donnees)} entrées chargées depuis la base de référence."
)


# --------------------------------------------------
# 6. Interface de recherche
# --------------------------------------------------

st.markdown("### Rechercher une entrée terminologique")

langue = st.radio(
    "Rechercher dans",
    ["Les deux langues", "Français", "Anglais"],
    horizontal=True,
)

requete = st.text_input(
    "Terme ou fragment de terme",
    placeholder="Ex. : énergie solaire / solar energy",
)

if requete.strip():

    champs = {
        "Français": ["Terme français"],
        "Anglais": ["English term"],
        "Les deux langues": [
            "Terme français",
            "English term",
        ],
    }[langue]

    recherche = normaliser_recherche(requete.strip())

    masque = pd.Series(
        False,
        index=donnees.index,
    )

    for champ in champs:
        valeurs = donnees[champ].map(normaliser_recherche)

        masque |= valeurs.str.contains(
            recherche,
            regex=False,
            na=False,
        )

    resultats = donnees.loc[masque]

    st.markdown(
        f"### Résultats : {len(resultats)}"
    )

    if resultats.empty:

        st.info(
            "Aucune entrée trouvée. Essayez un autre terme "
            "ou un fragment plus court."
        )

    else:

        for _, entree in resultats.iterrows():

            with st.expander(
                f"{entree['Terme français']} — "
                f"{entree['English term']} "
                f"(ID : {entree['ID']})"
            ):

                gauche, droite = st.columns(2)

                # Présentation française
                with gauche:

                    st.markdown("#### Français")

                    st.markdown(
                        f"**Terme :** {entree['Terme français']}"
                    )

                    st.markdown(
                        "**Catégorie grammaticale :** "
                        f"{entree['Catégorie grammaticale FR']}"
                    )

                    st.markdown("**Définition**")

                    st.write(
                        entree["Définition française"]
                    )

                # Présentation anglaise
                with droite:

                    st.markdown("#### English")

                    st.markdown(
                        f"**Term:** {entree['English term']}"
                    )

                    st.markdown(
                        "**Part of speech:** "
                        f"{entree['Part of speech EN']}"
                    )

                    st.markdown("**Definition**")

                    st.write(
                        entree["English definition"]
                    )

                st.caption(
                    f"Identifiant stable : {entree['ID']}"
                )

else:

    st.info(
        "Saisissez un terme en français ou en anglais "
        "pour consulter les entrées correspondantes."
    )


# --------------------------------------------------
# 7. Présentation scientifique
# --------------------------------------------------

st.divider()

st.markdown("### À propos du dictionnaire")

# Présentation générale
st.markdown("#### Présentation générale")

st.markdown("""
Ce dictionnaire terminologique bilingue anglais–français est consacré
au domaine des énergies renouvelables. Il a pour objectif de faciliter
la consultation et la compréhension des termes spécialisés employés
dans ce domaine.

Pour chaque entrée, il propose le terme français, sa catégorie
grammaticale, sa définition en français, le terme anglais correspondant,
sa catégorie grammaticale et sa définition en anglais.
""")

# Contenu et organisation
st.markdown("#### Contenu et organisation")

st.markdown("""
La base terminologique comprend **1 000 entrées**, dont **785 termes
complexes** et **215 termes simples**, organisées selon une structure
bilingue harmonisée. Chaque entrée est identifiée par un identifiant
unique afin de faciliter son repérage et la gestion des données.

Les informations affichées dans le dictionnaire proviennent de la base
terminologique de référence. Les termes et les définitions sont
reproduits sans modification par l’application.
""")

# Langues et domaine
st.markdown("#### Langues et domaine")

st.markdown("""
- **Langues :** français et anglais.
- **Domaine :** énergies renouvelables.
- **Type de ressource :** dictionnaire terminologique bilingue.
- **Version de la base :** V1.
- **Dernière mise à jour :** octobre 2026.
- **Mode d’utilisation :** consultation en ligne, en lecture seule.
""")

# Fonctionnement
st.markdown("#### Fonctionnement")

st.markdown("""
L’application permet de rechercher des termes dans les deux langues
et de consulter les informations terminologiques associées. Elle est
conçue pour faciliter l’accès aux données sur différents appareils,
sans nécessiter la création d’un compte utilisateur.

L’application ne permet ni de modifier les entrées ni d’ajouter de
nouveaux termes. Les résultats affichés dépendent de la version de la
base terminologique de référence.
""")

# Cadre scientifique
st.markdown("#### Cadre scientifique")

st.markdown("""
Cette ressource s’inscrit dans une démarche de description
terminologique bilingue du domaine des énergies renouvelables, en
mettant l’accent sur les termes complexes, qui constituent la majeure
partie de la base.

Elle constitue un outil de consultation destiné notamment aux
étudiants, aux chercheurs, aux traducteurs, aux rédacteurs techniques
et à toute personne intéressée par la terminologie spécialisée de ce
domaine.
""")

# Références et responsabilité scientifique
st.markdown("#### Références et responsabilité scientifique")

st.markdown("""
- **Autrice :** Bérénice KABORE.
- **Référence de la base :** *Glossaire Français-Anglais de la
  terminologie des énergies renouvelables*, version V1.
""")

# --------------------------------------------------
# 8. Licence, droits d'auteur et conditions d'utilisation
# --------------------------------------------------

st.divider()

st.markdown("### Licence, droits d’auteur et conditions d’utilisation")

st.markdown("""
**© 2026 Bérénice KABORE — Tous droits réservés.**

Le *Glossaire Français-Anglais de la terminologie des énergies
renouvelables*, version V1, ainsi que sa structure, son organisation
terminologique et les éléments originaux qui le composent, constituent
une ressource intellectuelle dont les droits appartiennent à son
autrice, Bérénice KABORE, sous réserve des droits
éventuellement détenus par des tiers sur certains contenus.

La consultation de ce dictionnaire est autorisée à des fins
personnelles, pédagogiques et de recherche, dans le respect des droits
de l’autrice et des présentes conditions d’utilisation.

**Sans autorisation écrite préalable de l’autrice, sont notamment
interdits :**

- La reproduction ou la copie substantielle, totale ou partielle,
  du dictionnaire ou de sa base terminologique.
- L’extraction systématique des entrées, des définitions ou des
  données en vue de constituer une autre base de données ou une
  ressource concurrente.
- La redistribution, la republication ou la mise à disposition
  du public de tout ou partie substantielle de la ressource.
- La modification, l’adaptation ou l’intégration substantielle des
  données dans un autre dictionnaire, glossaire, logiciel ou produit
  documentaire.
- Toute exploitation à des fins commerciales, notamment la vente,
  la revente, la commercialisation ou l’intégration des données
  dans un service ou un produit payant.

Toute utilisation dépassant le cadre de la consultation autorisée
doit faire l’objet d’une demande d’autorisation préalable auprès
de l’autrice. Les utilisations autorisées doivent respecter les
conditions expressément convenues.

Toute utilisation non autorisée susceptible de porter atteinte aux
droits protégés pourra donner lieu aux recours et actions prévus par
la législation applicable en matière de propriété intellectuelle.
""")

# Identification de l'autrice et de la ressource
st.markdown("""
**Autrice et titulaire des droits revendiqués :**
Bérénice KABORE.

**Ressource concernée :** *Glossaire Français-Anglais de la
terminologie des énergies renouvelables*, version V1.
""")

# Mention de protection en pied de section
st.caption(
    "© 2026 Bérénice KABORE. Tous droits réservés. "
    "Toute reproduction substantielle, redistribution ou exploitation "
    "commerciale est soumise à autorisation préalable, sous réserve "
    "des droits des tiers et des exceptions prévues par la "
    "législation applicable."
)
