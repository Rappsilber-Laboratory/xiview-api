from uuid import uuid4, UUID
from sqlalchemy import create_engine, MetaData
from sqlalchemy import Table as SATable
from create_db_schema import create_schema
from sqlalchemy_utils import database_exists


def Table(name, *args, **kw):
    """Return an SQLAlchemy table but that uses the lower case table name.
    This is a workaround for the "quote=False" argument not working properly for the postgresql
    dialect in SQLAlchemy.
    :param name: name of the table - will be forwarded as lower case string.
    """
    return SATable(name.lower(), *args, **kw)


class Writer:
    """Class for writing results to a relational database."""

    def __init__(self, connection_str, user_id=None, upload_id=None):
        """
        Initialises the database connection and the writer in general.

        :param connection_str: database connection string
        :param user_id: UUID of the UserAccount (postgresql specific)
        """
        # Connection setup.
        # The 'engine' in SQLAlchemy is a Factory and connection pool to the database.
        # It has lazy initialisation.
        self.engine = create_engine(connection_str)
        self.meta = MetaData()
        if upload_id:
            self.upload_id = upload_id
        else:
            self.upload_id = str(uuid4())
        # if user_id is not None and not isinstance(user_id, UUID):
        #     raise Exception('user_id must be a uuid!')
        self.user_id = str(user_id)
        # Create table schema if necessary (SQLite)
        if not database_exists(self.engine.url):
            create_schema(self.engine.url)

    def write_data(self, table, data):
        """
        Insert data into table.

        :param table: (str) Table name
        :param data: (list dict) data to insert.
        """
        table = Table(table, self.meta, autoload_with=self.engine, quote=False)
        with self.engine.connect() as conn:
            statement = table.insert().values(data)
            conn.execute(statement)
            conn.close()

    def write_mzid_info(self, spectra_formats,
                        provider, audits, samples, bib):
        """
        Update Upload row with mzid info.

        ToDo: have this explicitly or create update func?
        :param spectra_formats:
        :param provider:
        :param audits:
        :param samples:
        :param bib:
        :return:
        """
        upload = Table("Upload", self.meta, autoload_with=self.engine, quote=False)
        stmt = upload.update().where(upload.c.id == str(self.upload_id)).values(
            spectra_formats=spectra_formats,
            provider=provider,
            audits=audits,
            samples=samples,
            bib=bib
        )
        with self.engine.connect() as conn:
            conn.execute(stmt)

    def write_other_info(self, contains_crosslinks, upload_warnings):
        """
        Update Upload row with remaining info.

        ToDo: have this explicitly or create update func?
        :param contains_crosslinks:
        :param upload_warnings:
        :return:
        """
        upload = Table("Upload", self.meta, autoload_with=self.engine, quote=False)
        with self.engine.connect() as conn:
            stmt = upload.update().where(upload.c.id == str(self.upload_id)).values(
                contains_crosslinks=contains_crosslinks,
                upload_warnings=upload_warnings,
            )
            conn.execute(stmt)

    def fill_in_missing_scores(self):
        """
        ToDo: this needs to be adapted to sqlalchemy from old SQLite version
        """
        pass
        # try:
        #     cur.execute("""
        #       SELECT DISTINCT scoresJSON.key as scoreKey
        #       FROM spectrum_identifications, json_each(spectrum_identifications.scores)
        #       AS scoresJSON""")
        #
        #     all_scores = cur.fetchall()
        #     all_scores = set([str(x[0]) for x in all_scores])
        #
        #     inj_list = []
        #
        #     cur.execute('SELECT id, scores FROM spectrum_identifications')
        #     res = cur.fetchall()
        #
        #     for row in res:
        #         row_scores = json.loads(row[1])
        #         missing = all_scores - set(row_scores.keys())
        #
        #         if len(missing) > 0:
        #             missing_dict = {key: -1 for key in missing}
        #             row_scores.update(missing_dict)
        #             inj_list.append([json.dumps(row_scores), row[0]])
        #             # cur.execute('UPDATE identifications SET allScores=? WHERE id = row[0]',
        #             json.dumps(row_scores))
        #
        #     cur.executemany("""
        #         UPDATE spectrum_identifications
        #         SET `scores` = ?
        #         WHERE `id` = ?""", inj_list)
        #
        #     con.commit()
        #
        # except sqlite3.Error as e:
        #     raise DBException(e.message)
        # pass