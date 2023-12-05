import psycopg2
from fastapi import APIRouter
from psycopg2.extras import RealDictCursor
import logging

from app.routes.shared import get_db_connection, get_most_recent_upload_ids

pdbdev_router = APIRouter()

app_logger = logging.getLogger(__name__)

@pdbdev_router.get('/projects/{project_id}/sequences', tags=["PDB-Dev"])
async def sequences(project_id):
    """
    Get all sequences belonging to a project.

    :param project_id: identifier of a project,
        for ProteomeXchange projects this is the PXD****** accession
    :return: JSON object with all dbref id, mzIdentML file it came from and sequences
    """

    most_recent_upload_ids = get_most_recent_upload_ids(project_id)

    conn = None
    mzid_rows = []
    try:
        # connect to the PostgreSQL server and create a cursor
        conn = await get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        sql = """SELECT dbseq.id, u.identification_file_name, dbseq.sequence
                    FROM upload AS u
                    JOIN dbsequence AS dbseq ON u.id = dbseq.upload_id
                    INNER JOIN peptideevidence pe ON dbseq.id = pe.dbsequence_ref AND dbseq.upload_id = pe.upload_id
                 WHERE u.id = ANY (%s)
                 AND pe.is_decoy = false
                 GROUP by dbseq.id, dbseq.sequence, u.identification_file_name;"""

        print(sql)
        cur.execute(sql, [most_recent_upload_ids])
        mzid_rows = cur.fetchall()

        print("finished")
        # close the communication with the PostgreSQL
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()
            print('Database connection closed.')
        return {"data": mzid_rows}


@pdbdev_router.get('/projects/{project_id}/residue-pairs/psm-level/{passing_threshold}', tags=["PDB-Dev"])
async def get_psm_level_residue_pairs(project_id, passing_threshold):
    """
    Get all residue pairs (based on PSM level data) belonging to a project.

    There will be multiple entries for identifications with
    positional uncertainty of peptide in protein sequences.
    :param project_id: identifier of a project,
    for ProteomeXchange projects this is the PXD****** accession
    :param passing_threshold: valid values: passing, all
        if 'passing' return residue pairs that passed the threshold
        if 'all' return all residue pairs
    :return:
    """
    if passing_threshold not in ['passing', 'all']:
        return f"Invalid value for passing_threshold: {passing_threshold}. " \
               f"Valid values are: passing, all", 400

    most_recent_upload_ids = get_most_recent_upload_ids(project_id)

    conn = None
    data = {}
    try:
        # connect to the PostgreSQL server and create a cursor
        conn = await get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        sql = """SELECT si.id, u.identification_file_name as file, si.pass_threshold as pass,
pe1.dbsequence_ref as prot1, (pe1.pep_start + mp1.link_site1 - 1) as pos1,
pe2.dbsequence_ref as prot2, (pe2.pep_start + mp2.link_site1 - 1) as pos2
FROM spectrumidentification si INNER JOIN
modifiedpeptide mp1 ON si.pep1_id = mp1.id AND si.upload_id = mp1.upload_id INNER JOIN
peptideevidence pe1 ON mp1.id = pe1.peptide_ref AND mp1.upload_id = pe1.upload_id INNER JOIN
modifiedpeptide mp2 ON si.pep2_id = mp2.id AND si.upload_id = mp2.upload_id INNER JOIN
peptideevidence pe2 ON mp2.id = pe2.peptide_ref AND mp2.upload_id = pe2.upload_id INNER JOIN
upload u on u.id = si.upload_id
where u.id = ANY (%s) and mp1.link_site1 > 0 and mp2.link_site1 > 0 AND pe1.is_decoy = false AND pe2.is_decoy = false
"""
        # problem above in u.project_id

        if passing_threshold.lower() == 'passing':
            sql += " AND si.pass_threshold = true"
        sql += ";"
        print(sql)
        cur.execute(sql, [most_recent_upload_ids])
        mzid_rows = cur.fetchall()
        data["data"] = mzid_rows

        print("finished")
        # close the communication with the PostgreSQL
        cur.close()
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()
            print('Database connection closed.')
        return data

#
# @pdb_dev_router.get('/projects/{project_id}/residue-pairs/reported')
# def get_reported_residue_pairs(project_id):
#     """
#     Get all residue-pairs reported for a project
#     from the ProteinDetectionList element(s).
#
#     :param project_id: identifier of a project,
#         for ProteomeXchange projects this is the PXD****** accession
#     :return:
#     """
#     return "Not Implemented", 501


@pdbdev_router.get('/projects/{project_id}/reported-thresholds', tags=["PDB-Dev"])
async def get_reported_thresholds(project_id):
    """
    Get all reported thresholds for a project.

    :param project_id: identifier of a project,
        for ProteomeXchange projects this is the PXD****** accession
    :return:
    """
    return "Not Implemented", 501