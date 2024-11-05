import logging
import logging.config
import struct

import fastapi
from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
import orjson
from psycopg2.extras import RealDictCursor
from sqlalchemy.orm import session, Session
from typing import List, Any, Optional

from models.upload import Upload
from app.routes.shared import get_db_connection, get_most_recent_upload_ids, log_execution_time_async
from index import get_session
from db_config_parser import get_xiview_base_url

xiview_data_router = APIRouter()


class EndpointFilter(logging.Filter):
    """
    Define the filter to stop logging for visualisation endpoint which will be called very frequently
    and log file will be flooded with this endpoint request logs
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.args and len(record.args) >= 3 and not str(record.args[2]).__contains__("/data/visualisations/")


logger = logging.getLogger(__name__)
logging.getLogger("uvicorn.access").addFilter(EndpointFilter())


def log_json_size(json_bytes, name):
    json_size_mb = len(json_bytes) / (1024 * 1024)
    logger.info(f"uncompressed size of json {name}: {json_size_mb} Mb")


async def execute_query(query: str, params: Optional[List[Any]] = None, fetch_one: bool = False):
    """
    Execute a query and return the result
    :param query: the query to execute
    :param params: the parameters to pass to the query
    :param fetch_one: whether to fetch one result or all
    :return: the result of the query
    """
    conn = None
    try:
        conn = await get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            result = cur.fetchone() if fetch_one else cur.fetchall()
        conn.commit()
        return result
    except Exception as e:
        logging.error(f"Database operation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database operation failed")
    finally:
        conn.close()


@xiview_data_router.get('/get_peaklist', tags=["xiVIEW"])
async def get_peaklist(id, sd_ref, upload_id):
    query = "SELECT intensity, mz FROM spectrum WHERE id = %s AND spectra_data_id = %s AND upload_id = %s"
    data = await execute_query(query, [id, sd_ref, upload_id], fetch_one=True)
    # Create a new dictionary to store the unpacked values
    unpacked_data = {
        "intensity": struct.unpack('%sd' % (len(data['intensity']) // 8), data['intensity']),
        "mz": struct.unpack('%sd' % (len(data['mz']) // 8), data['mz'])
    }
    return Response(orjson.dumps(unpacked_data), media_type='application/json')


@xiview_data_router.get('/visualisations/{project_id}', tags=["xiVIEW"])
def visualisations(project_id: str, request: Request, session: Session = Depends(get_session)):
    xiview_base_url = get_xiview_base_url()
    project_detail = session.query(Upload) \
        .filter(Upload.project_id == project_id) \
        .all()
    datasets = []
    processed_filenames = set()
    for record in project_detail:
        filename = record.identification_file_name
        if filename not in processed_filenames:
            datafile = {
                "filename": filename,
                "visualisation": "cross-linking",  # todo - we're not hyphenating crosslinking
                "link": (xiview_base_url + "?project=" + project_id + "&file=" +
                         str(filename))
            }
            datasets.append(datafile)
            processed_filenames.add(filename)

    return datasets


@log_execution_time_async
@xiview_data_router.get('/get_xiview_metadata', tags=["xiVIEW"])
async def get_xiview_metadata(project, file=None):
    """
    Get the metadata for the xiVIEW visualisation.
    URLs have the following structure:
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_metadata?project=PXD020453&file=Cullin_SDA_1pcFDR.mzid
    Users may provide only projects, meaning we need to have an aggregated view.
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_metadata?project=PXD020453

    :return: json of the metadata
    """
    logger.info(f"get_xiview_metadata for {project}, file: {file}")
    most_recent_upload_ids = await get_most_recent_upload_ids(project, file)
    metadata = {}
    # get Upload(s) for each id
    query = """SELECT u.id AS id,
                    u.project_id,
                    u.identification_file_name,
                    u.provider,
                    u.audit_collection,
                    u.analysis_sample_collection,
                    u.bib,
                    u.spectra_formats,
                    u.contains_crosslinks,
                    u.upload_warnings AS warnings
                FROM upload u
                WHERE u.id = ANY(%s);"""
    metadata["mzidentml_files"] = await execute_query(query, [most_recent_upload_ids])
    # get analysiscollectionspectrumidentification(s) for each id
    query = """SELECT ac.upload_id,
                    ac.spectrum_identification_list_ref,
                    ac.spectrum_identification_protocol_ref,
                    ac.spectra_data_refs,
                    ac.search_database_refs
                FROM analysiscollectionspectrumidentification ac
                WHERE ac.upload_id = ANY(%s);"""
    metadata["analysis_collections"] = await execute_query(query, [most_recent_upload_ids])
    # get SpectrumIdentificationProtocol(s) for each id
    query = """SELECT sip.id AS id,
                    sip.sip_ref,    
                    sip.upload_id,
                    sip.frag_tol,
                    sip.frag_tol_unit,
                    sip.additional_search_params,
                    sip.analysis_software,
                    sip.threshold
                FROM spectrumidentificationprotocol sip
                WHERE sip.upload_id = ANY(%s);"""
    metadata["spectrum_identification_protocols"] = await execute_query(query, [most_recent_upload_ids])
    # spectradata for each id
    query = """SELECT *
                FROM spectradata sd
                WHERE sd.upload_id = ANY(%s);"""
    metadata["spectra_data"] = await execute_query(query, [most_recent_upload_ids])
    # enzymes
    query = """SELECT *
                FROM enzyme e
                WHERE e.upload_id = ANY(%s);"""
    metadata["enzymes"] = await execute_query(query, [most_recent_upload_ids])
    # search modifications
    query = """SELECT *
                FROM searchmodification sm
                WHERE sm.upload_id = ANY(%s);"""
    metadata["search_modifications"] = await execute_query(query, [most_recent_upload_ids])
    return Response(orjson.dumps(metadata), media_type='application/json')


@log_execution_time_async
@xiview_data_router.get('/get_xiview_matches', tags=["xiVIEW"])
async def get_xiview_matches(project, file=None):
    """
    Get the passing matches.
    URLs have the following structure:
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_matches?project=PXD020453&file=Cullin_SDA_1pcFDR.mzid
    Users may provide only projects, meaning we need to have an aggregated  view.
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_matches?project=PXD020453

    :return: json of the matches
    """
    logger.info(f"get_xiview_matches for {project}, file: {file}")
    most_recent_upload_ids = await get_most_recent_upload_ids(project, file)
    # todo - rename 'si' to 'm'
    query = """WITH submodpep AS (SELECT * FROM modifiedpeptide WHERE upload_id = ANY(%s) AND link_site1 > -1)
    SELECT si.id AS id, si.pep1_id AS pi1, si.pep2_id AS pi2,
                    si.scores AS sc,
                    cast (si.upload_id as text) AS si,
                    si.calc_mz AS c_mz,
                    si.charge_state AS pc_c,
                    si.exp_mz AS pc_mz,
                    si.spectrum_id AS sp,
                    si.spectra_data_id AS sd,
                    si.pass_threshold AS p,
                    si.rank AS r,
                    si.sip_id AS sip                
                FROM match si 
                INNER JOIN submodpep mp1 ON si.upload_id = mp1.upload_id AND si.pep1_id = mp1.id 
                INNER JOIN submodpep mp2 ON si.upload_id = mp2.upload_id AND si.pep2_id = mp2.id 
                WHERE si.upload_id = ANY(%s) 
                AND si.pass_threshold = TRUE 
                AND mp1.link_site1 > -1
                AND mp2.link_site1 > -1;"""
    data = await execute_query(query, [most_recent_upload_ids, most_recent_upload_ids])
    return Response(orjson.dumps(data), media_type='application/json')


@log_execution_time_async
@xiview_data_router.get('/get_xiview_peptides', tags=["xiVIEW"])
async def get_xiview_peptides(project, file=None):
    """
    Get all the peptides.
    URLs have the following structure:
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_peptides?project=PXD020453&file=Cullin_SDA_1pcFDR.mzid
    Users may provide only projects, meaning we need to have an aggregated view.
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_peptides?project=PXD020453

    :return: json of the peptides
    """
    logger.info(f"get_xiview_peptides for {project}, file: {file}")
    most_recent_upload_ids = await get_most_recent_upload_ids(project, file)

    query = """with submatch as (select pep1_id, pep2_id, upload_id from match where upload_id = ANY(%s) and pass_threshold = true), 
pep_ids as (select upload_id, pep1_id from submatch  union select upload_id, pep2_id from submatch),
subpp AS (select * from peptideevidence WHERE upload_id = ANY(%s))
select mp.id,
                cast(mp.upload_id as text) AS u_id,
                mp.base_sequence AS seq,
                array_agg(pp.dbsequence_id) AS prt,
                array_agg(pp.pep_start) AS pos,
                array_agg(pp.is_decoy) AS dec,
                mp.link_site1 AS ls1,
                mp.link_site2 AS ls2,
                mp.mod_accessions as m_as,
                mp.mod_positions as m_ps,
                mp.mod_monoiso_mass_deltas as m_ms,
                mp.crosslinker_modmass as cl_m from pep_ids pi
inner join modifiedpeptide mp on mp.upload_id = pi.upload_id and pi.pep1_id = mp.id
                    JOIN subpp AS pp
                    ON mp.upload_id = pp.upload_id AND mp.id = pp.peptide_id 
                    GROUP BY mp.id, mp.upload_id, mp.base_sequence;"""
    data = await execute_query(query, [most_recent_upload_ids, most_recent_upload_ids])
    return Response(orjson.dumps(data), media_type='application/json')


@log_execution_time_async
@xiview_data_router.get('/get_xiview_proteins', tags=["xiVIEW"])
async def get_xiview_proteins(project, file=None):
    """
    Get all the proteins.
    URLs have the following structure:
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_proteins?project=PXD020453&file=Cullin_SDA_1pcFDR.mzid
    Users may provide only projects, meaning we need to have an aggregated  view.
    https: // www.ebi.ac.uk / pride / archive / xiview / get_xiview_proteins?project=PXD020453

    :return: json of the proteins
    """
    logger.info(f"get_xiview_proteins for {project}, file: {file}")
    most_recent_upload_ids = await get_most_recent_upload_ids(project, file)
    query = """SELECT id, name, accession, sequence,
                     cast(upload_id as text) AS search_id, description FROM dbsequence
                     WHERE upload_id = ANY(%s)
                ;"""
    data = await execute_query(query, [most_recent_upload_ids])
    return Response(orjson.dumps(data), media_type='application/json')


@log_execution_time_async
@xiview_data_router.get('/get_datasets', tags=["xiVIEW"])
async def get_datasets():
    query = """SELECT DISTINCT project_id, identification_file_name FROM upload;"""
    data = await execute_query(query)
    return Response(orjson.dumps(data), media_type='application/json')
