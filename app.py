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
    page_title="Dictionnaire terminologique bilingue | Énergies renouvelables",
    page_icon="📚",
    layout="wide",
)

# L'identifiant du fichier n'est pas une clé privée. Il peut toutefois
# être conservé dans les secrets Streamlit pour centraliser la configuration.
FILE_ID = st.secrets.get("drive", {}).get(
    "file_id",
    "1CSW3D8w6SGB-eZ0vR9U-MvNzahtOojhY",
)

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
# 2. Chargement depuis Google Drive
# --------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def charger_donnees(file_id):
    """Charge en mémoire la feuille terminologique depuis Google Drive."""

    credentials = service_account.Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )

    drive = build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    metadata = drive.files().get(
        fileId=file_id,
        fields="id,name,mimeType",
    ).execute()

    mime_type = metadata["mimeType"]

    if mime_type == "application/vnd.google-apps.spreadsheet":
        request = drive.files().export_media(
            fileId=file_id,
            mimeType=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )
    else:
        request = drive.files().get_media(fileId=file_id)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    termine = False

    while not termine:
        _, termine = downloader.next_chunk()

    buffer.seek(0)

    df = pd.read_excel(
        buffer,
        sheet_name="Glossaire bilingue",
        engine="openpyxl",
    )

    if list(df.columns) != COLONNES:
        raise ValueError("La structure des colonnes est incorrecte.")

    if df.empty:
        raise ValueError("La base terminologique est vide.")

    if df.isna().any().any():
        raise ValueError("La base terminologique contient des cellules vides.")

    if df["ID"].duplicated().any():
        raise ValueError("La base terminologique contient des identifiants dupliqués.")

    champs_texte = [col for col in COLONNES if col != "ID"]
    for champ in champs_texte:
        if not df[champ].map(
            lambda valeur: isinstance(valeur, str) and bool(valeur.strip())
        ).all():
            raise ValueError("Certains champs textuels sont vides ou invalides.")

    return df


# --------------------------------------------------
# 3. Normalisation de la recherche
# --------------------------------------------------

def normaliser_recherche(texte):
    """Ignore la casse et les accents pour faciliter la recherche."""
    texte = str(texte).casefold()
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(
        caractere
        for caractere in texte
        if not unicodedata.combining(caractere)
    )


# --------------------------------------------------
# 4. En-tête et présentation générale
# --------------------------------------------------

st.title("Dictionnaire terminologique bilingue")
st.subheader("Anglais–français du domaine des énergies renouvelables")
st.caption("Renewable energy · Ressource de consultation terminologique · Version V1")

st.markdown(
    """
    Cette ressource permet de consulter les termes spécialisés des énergies
    renouvelables en français et en anglais, ainsi que leurs définitions
    et catégories grammaticales.
    """
)


# --------------------------------------------------
# 5. Chargement de la base
# --------------------------------------------------

try:
    with st.spinner("Chargement du dictionnaire…"):
        donnees = charger_donnees(FILE_ID)

except HttpError:
    st.error(
        "Le dictionnaire n'a pas pu être chargé. "
        "Veuillez réessayer ultérieurement."
    )
    st.caption(
        "Si le problème persiste, l'équipe responsable doit vérifier "
        "les autorisations Google Drive et la configuration de l'application."
    )
    st.stop()

except Exception:
    st.error(
        "Le dictionnaire est momentanément indisponible. "
        "Veuillez réessayer ultérieurement."
    )
    st.caption("Le détail technique n'est pas affiché sur cette page publique.")
    st.stop()

nombre_entrees = len(donnees)
nombre_formes = int(
    (
        donnees["Terme français"].astype(str).str.strip().ne("")
        & donnees["English term"].astype(str).str.strip().ne("")
    ).sum()
    * 2
)

st.success("Le dictionnaire est disponible.")

col_stat1, col_stat2, col_stat3 = st.columns(3)
with col_stat1:
    st.metric("Entrées terminologiques", f"{nombre_entrees:,}".replace(",", " "))
with col_stat2:
    st.metric("Nombre total de termes", f"{nombre_formes:,}".replace(",", " "))
with col_stat3:
    st.metric("Langues", "Français · English")

st.caption(
    "Chaque entrée associe un terme français à son équivalent anglais, "
    "avec les informations terminologiques correspondantes."
)


# --------------------------------------------------
# 6. Interface de recherche
# --------------------------------------------------

st.divider()
st.markdown("### Rechercher dans le dictionnaire")

langue = st.radio(
    "Langue de recherche",
    ["Les deux langues", "Français", "Anglais"],
    horizontal=True,
)

requete = st.text_input(
    "Saisir un terme ou une partie du terme",
    placeholder="Ex. : énergie solaire / solar energy",
    help=(
        "La recherche ignore les différences entre majuscules, minuscules "
        "et accents. Un fragment de terme peut être utilisé."
    ),
)

if requete.strip():
    champs = {
        "Français": ["Terme français"],
        "Anglais": ["English term"],
        "Les deux langues": ["Terme français", "English term"],
    }[langue]

    recherche = normaliser_recherche(requete.strip())
    masque = pd.Series(False, index=donnees.index)

    for champ in champs:
        valeurs = donnees[champ].map(normaliser_recherche)
        masque |= valeurs.str.contains(recherche, regex=False, na=False)

    resultats = donnees.loc[masque]
    st.markdown(f"### Résultats : {len(resultats)}")

    if resultats.empty:
        st.info(
            "Aucune entrée ne correspond à cette recherche. "
            "Essayez un autre terme ou un fragment plus court."
        )
    else:
        for _, entree in resultats.iterrows():
            titre_fiche = (
                f"{entree['Terme français']} — {entree['English term']} "
                f"(ID : {entree['ID']})"
            )

            with st.expander(titre_fiche):
                gauche, droite = st.columns(2, gap="large")

                with gauche:
                    st.markdown("#### Français")
                    st.markdown(f"**Terme :** {entree['Terme français']}")
                    st.markdown(
                        "**Catégorie grammaticale :** "
                        f"{entree['Catégorie grammaticale FR']}"
                    )
                    st.markdown("**Définition**")
                    st.write(entree["Définition française"])

                with droite:
                    st.markdown("#### English")
                    st.markdown(f"**Term:** {entree['English term']}")
                    st.markdown(
                        "**Part of speech:** "
                        f"{entree['Part of speech EN']}"
                    )
                    st.markdown("**Definition**")
                    st.write(entree["English definition"])

                st.caption(f"Identifiant de l'entrée : {entree['ID']}")
else:
    st.info(
        "Saisissez un terme en français ou en anglais pour afficher "
        "les entrées correspondantes."
    )


# --------------------------------------------------
# 7. Présentation scientifique
# --------------------------------------------------

st.divider()
st.markdown("## À propos du dictionnaire")

with st.expander("Présentation générale", expanded=True):
    st.markdown(
        """
        Ce dictionnaire terminologique bilingue anglais–français est consacré
        au domaine des énergies renouvelables. Il a pour objectif de faciliter
        la consultation et la compréhension des termes spécialisés employés
        dans ce domaine.

        Pour chaque entrée, il propose le terme français, sa catégorie
        grammaticale, sa définition en français, le terme anglais correspondant,
        sa catégorie grammaticale et sa définition en anglais.
        """
    )

with st.expander("Contenu et organisation"):
    st.markdown(
        f"""
        La base terminologique comprend **{nombre_entrees:,} entrées bilingues**
        et **{nombre_formes:,} formes terminologiques au total**.
        Elle comprend **1567 termes complexes** et **433 termes simples**,
        organisés selon une structure bilingue harmonisée.

        Chaque entrée possède un identifiant unique afin de faciliter son
        repérage et la gestion des données. Les informations affichées
        proviennent de la base terminologique de référence.
        """.replace(",", " ")
    )

with st.expander("Langues et domaine"):
    st.markdown(
        """
        - **Langues :** français et anglais.
        - **Domaine :** énergies renouvelables.
        - **Type de ressource :** dictionnaire terminologique bilingue.
        - **Version de la base :** V1.
        - **Dernière mise à jour déclarée :** octobre 2026.
        - **Mode d’utilisation :** consultation en ligne, en lecture seule.
        """
    )

with st.expander("Fonctionnement"):
    st.markdown(
        """
        L’application permet de rechercher des termes dans les deux langues
        et de consulter les informations terminologiques associées. Elle est
        conçue pour être accessible sur différents appareils, sans création
        de compte utilisateur.

        L’application ne permet ni de modifier les entrées ni d’ajouter de
        nouveaux termes. Les résultats affichés dépendent de la version de la
        base terminologique de référence.
        """
    )

with st.expander("Cadre scientifique"):
    st.markdown(
        """
        Cette ressource s’inscrit dans une démarche de description
        terminologique bilingue du domaine des énergies renouvelables, en
        mettant l’accent sur les termes complexes, qui constituent la majeure
        partie de la base.

        Elle constitue un outil de consultation destiné notamment aux
        étudiants, aux chercheurs, aux traducteurs, aux rédacteurs techniques
        et à toute personne intéressée par la terminologie spécialisée de ce
        domaine.
        """
    )

with st.expander("Références et responsabilité scientifique"):
    st.markdown(
        """
        - **Autrice :** Bérénice KABORE.
        - **Référence de la base :** *Glossaire Français-Anglais de la
          terminologie des énergies renouvelables*, version V1.
        """
    )



# --------------------------------------------------
# 8. Licence, droits d'auteur et conditions d'utilisation
# --------------------------------------------------

st.divider()
st.markdown("## Licence, droits d’auteur et conditions d’utilisation")

with st.expander("Consulter les conditions d’utilisation", expanded=False):
    st.markdown(
        """
        **© 2026 Bérénice KABORE — Tous droits réservés, sous réserve
        des droits des tiers et des dispositions légales applicables.**

        ## 1. Présentation de la ressource

        Le *Glossaire français–anglais de la terminologie des énergies
        renouvelables*, version V1, est une ressource terminologique
        bilingue élaborée par Bérénice KABORE.

        La ressource comprend des termes français et anglais, leurs
        catégories grammaticales, leurs définitions et une organisation
        permettant de consulter les correspondances terminologiques entre
        les deux langues.

        La protection revendiquée porte notamment sur les éléments originaux
        de la ressource qui remplissent les conditions de protection prévues
        par la législation applicable, tels que les formulations originales,
        la sélection et l’organisation des données, ainsi que la structure
        de la base, dans la mesure où ces éléments sont juridiquement
        protégeables.

        Les termes, concepts, faits et données pris isolément ne sont pas
        nécessairement protégés par le droit d’auteur. Les droits
        éventuellement détenus par des tiers sur certains contenus demeurent
        réservés.

        ## 2. Consultation autorisée

        La consultation du dictionnaire en ligne est autorisée à des fins
        personnelles, pédagogiques, universitaires et de recherche, dans
        le respect des présentes conditions et de la législation applicable.

        Les utilisateurs peuvent notamment consulter les entrées et les
        définitions, effectuer des recherches terminologiques et citer des
        éléments de la ressource dans le cadre de travaux scientifiques ou
        pédagogiques, dans les limites prévues par la loi.

        Lorsque cela est pertinent, la référence à la ressource doit mentionner :

        - **Autrice :** Bérénice KABORE.
        - **Titre :** *Glossaire français–anglais de la terminologie des
          énergies renouvelables*.
        - **Version :** V1.
        - **Adresse de consultation :**
          [Dictionnaire terminologique en ligne](https://dictionnaire-terminologique-energies-renouvelables-dg9omb8rqmj.streamlit.app/)

        La citation de la source ne vaut pas autorisation de reproduire ou
        de redistribuer une partie substantielle de la base.

        ## 3. Réutilisations soumises à autorisation

        Sous réserve des droits des tiers, des exceptions et des limitations
        prévues par la législation applicable, l’autorisation écrite préalable
        de l’autrice est requise pour les utilisations portant sur les éléments
        protégés de la ressource qui dépassent le cadre de la consultation
        autorisée, notamment :

        - La reproduction ou la redistribution d’une partie substantielle du
          dictionnaire ou de sa base terminologique.
        - L’extraction ou la réutilisation systématique des données en vue de
          constituer ou d’alimenter une autre base terminologique, un glossaire
          ou une ressource documentaire.
        - La republication ou la mise à disposition du public d’une partie
          substantielle de la ressource.
        - L’intégration substantielle des éléments protégés dans un dictionnaire,
          un logiciel, un produit documentaire ou un service tiers.
        - L’exploitation commerciale des éléments protégés de la ressource.

        Toute demande d’autorisation doit préciser la nature de l’utilisation
        envisagée, les éléments concernés, le contexte de diffusion et, le cas
        échéant, les modalités de commercialisation.

        Aucune disposition des présentes conditions ne vise à interdire les
        utilisations qui sont autorisées par la législation applicable,
        notamment les exceptions légales pertinentes.

        ## 4. Intégrité et attribution

        Les utilisateurs sont invités à respecter l’intégrité des éléments
        cités et à attribuer correctement la ressource à son autrice lorsqu’ils
        s’y réfèrent.

        Toute présentation d’extraits ne doit pas créer de confusion quant à
        leur origine, à leur contexte ou à la responsabilité scientifique
        de l’autrice.

        Les présentes conditions ne confèrent aucun droit sur les contenus
        appartenant à des tiers et ne remplacent pas les autorisations
        éventuellement nécessaires pour leur utilisation.

        ## 5. Évolution de la ressource

        Le dictionnaire est proposé comme un outil de consultation en ligne.
        Son contenu peut évoluer au fil des mises à jour de la base
        terminologique.

        La version actuellement présentée est la **version V1**. Les
        informations relatives à la version et à la date de mise à jour
        doivent être interprétées comme se rapportant à la base de référence
        effectivement publiée.

        ## 6. Contact et demandes d’autorisation

        Pour toute question concernant la ressource ou pour toute demande
        d’autorisation relative à sa reproduction, sa redistribution, son
        adaptation ou son exploitation, vous pouvez contacter l’autrice :

        **Bérénice KABORE**

        **Courriel :** [berenicekabore@gmail.com](mailto:berenicekabore@gmail.com)
        """
    )

# --------------------------------------------------
# 9. Contact et demandes d'autorisation
# --------------------------------------------------

st.divider()
st.markdown("## Contact et demandes d’autorisation")

st.markdown(
    """
    Pour toute question concernant le dictionnaire, la base terminologique,
    les données publiées ou les conditions de réutilisation, vous pouvez
    contacter l’autrice.

    Pour toute demande d’autorisation relative à la reproduction, à la
    redistribution, à l’adaptation ou à l’exploitation de la base
    terminologique, veuillez préciser l’objet de votre demande, les éléments
    concernés et l’utilisation envisagée.
    """
)

st.markdown(
    "**Autrice :** Bérénice KABORE  \n"
    "**Courriel :** [berenicekabore@gmail.com](mailto:berenicekabore@gmail.com)"
)

st.caption(
    "© 2026 Bérénice KABORE. Tous droits réservés, sous réserve des droits "
    "des tiers et des exceptions prévues par la législation applicable."
)
