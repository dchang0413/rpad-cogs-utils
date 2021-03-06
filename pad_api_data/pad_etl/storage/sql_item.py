from datetime import datetime, date
import decimal
import json
import time

from enum import Enum


def object_to_sql_params(obj):
    d = obj if type(obj) == dict else obj.__dict__
    # Defensive copy since we're updating this dict
    d = dict(d)
    d = process_col_mappings(type(obj), d, reverse=True)
    new_d = {}
    for k, v in d.items():
        new_val = value_to_sql_param(v)
        if new_val is not None:
            new_d[k] = new_val
    return new_d


def value_to_sql_param(v):
    if v is None:
        return 'NULL'
    elif type(v) == str:
        clean_v = v.replace("'", r"''")
        return "'{}'".format(clean_v)
    elif type(v) in (int, float, decimal.Decimal):
        return '{}'.format(v)
    elif type(v) in [date]:
        return "'{}'".format(v.isoformat())
    elif type(v) in [datetime]:
        return "'{}'".format(v.replace(tzinfo=None).isoformat())
    elif type(v) in [bool]:
        return str(v)
    else:
        return None


def _col_compare(col):
    return col + ' = ' + _col_value_ref(col)


def _col_value_ref(col):
    return '{' + col + '}'


def _col_name_ref(col):
    return '`' + col + '`'


def _tbl_name_ref(table_name):
    return '`' + table_name + '`'


def generate_insert_sql(table_name, cols, item):
    sql = 'INSERT INTO {}'.format(_tbl_name_ref(table_name))
    sql += ' (' + ', '.join(map(_col_name_ref, cols)) + ')'
    sql += ' VALUES (' + ', '.join(map(_col_value_ref, cols)) + ')'
    return sql.format(**object_to_sql_params(item))


# This could maybe move to a class method on SqlItem?
# Fix usage in load_x_object in db_util.
def process_col_mappings(obj_type, d, reverse=False):
    if hasattr(obj_type, 'COL_MAPPINGS'):
        mappings = obj_type.COL_MAPPINGS
        if reverse:
            mappings = {v: k for k, v in mappings.items()}

        for k, v in mappings.items():
            d[v] = d[k]
            d.pop(k)
    return d


def full_columns(o: 'SqlItem', remove_cols=[], add_cols=[]):
    cols = set(vars(o).keys())
    if o.uses_local_primary_key():
        cols.discard(o._key())
    cols.discard('tstamp')
    # Do something about tstamp in SqlItem insert or update
    cols = set([x for x in cols if not x.startswith('resolved')])
    cols = cols.difference(remove_cols)
    cols = cols.union(add_cols)

    if hasattr(type(o), 'COL_MAPPINGS'):
        mappings = type(o).COL_MAPPINGS
        for k, v in mappings.items():
            cols.discard(v)
            cols.add(k)

    return list(cols)


def dump_helper(x):
    if isinstance(x, Enum):
        return str(x)
    elif hasattr(x, '__dict__'):
        return vars(x)
    else:
        return repr(x)


def dump(obj):
    return json.dumps(obj, indent=4, sort_keys=True, default=dump_helper)


def key_and_cols_compare(item: 'SqlItem', cols=[], include_key=True):
    if include_key and item._key() not in cols:
        cols = [item._key()] + cols

    sql = 'SELECT {} FROM {} WHERE'.format(item._key(), item._table())
    sql += ' ' + ' AND '.join(map(_col_compare, cols))
    formatted_sql = sql.format(**object_to_sql_params(item))
    fixed_sql = formatted_sql.replace('= NULL', 'is NULL')

    return fixed_sql


class SqlItem(object):
    def key_value(self):
        return getattr(self, self._key()) if self._key() else None

    def needs_insert(self):
        if not self.uses_local_primary_key():
            raise Exception('Should not call this function, uses FK primary Key')
        key_val = self.key_value()
        return key_val is None or key_val == 0

    def uses_local_primary_key(self):
        """Controls insert logic.

        If true, an insert is needed if the primary key is missing.
        If false, an insert is needed if the primary key is set but not found in the table.
        """
        return True

    def uses_alternate_key_lookup(self):
        """Controls insert logic.

        If true, an insert is needed if the 'exists' sql fails, which will also be used to
        retrieve the primary key.
        """
        return False

    def exists_sql(self):
        return key_and_cols_compare(self)

    def needs_update_sql(self, include_key=True):
        update_cols = self._update_columns()
        if update_cols is None:
            return False

        return key_and_cols_compare(self, cols=update_cols, include_key=include_key)

    # TODO: move to dbutil
    def update_sql(self):
        cols = self._update_columns()
        if not cols:
            return None  # Update not supported

        # If an item is timestamped, modify the timestamp on every update
        if hasattr(self, 'tstamp'):
            if 'tstamp' not in cols:
                cols = cols + ['tstamp']
            self.tstamp = time.time() * 1000

        sql = 'UPDATE {}'.format(self._table())
        sql += ' SET ' + ', '.join(map(_col_compare, cols))
        sql += ' WHERE ' + _col_compare(self._key())
        return sql.format(**object_to_sql_params(self))

    def insert_sql(self):
        cols = self._insert_columns()
        if hasattr(self, 'tstamp'):
            if 'tstamp' not in cols:
                cols = cols + ['tstamp']
            self.tstamp = time.time() * 1000
        return generate_insert_sql(self._table(), cols, self)

    def set_key_value(self, key_value):
        setattr(self, self._key(), key_value)

    def _table(self):
        raise NotImplemented('no table name set')

    def _key(self):
        raise NotImplemented('no key name set')

    def _insert_columns(self):
        raise NotImplemented('no insert columns set')

    def _update_columns(self):
        return None

    def _key_lookup_sql(self):
        raise NotImplemented('no key lookup sql')


class SimpleSqlItem(SqlItem):
    def __repr__(self):
        return dump(self)

    def _table(self):
        return type(self).TABLE

    def _key(self):
        return type(self).KEY_COL

    def _insert_columns(self):
        return full_columns(self)

    def _update_columns(self):
        return full_columns(self, remove_cols=[self._key])
