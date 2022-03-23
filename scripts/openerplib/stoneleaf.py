# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (C) 2015 Ethan Furman
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
##############################################################################

import os as _os
import sys as _sys
import aenum as _aenum
from collections import defaultdict, OrderedDict
from warnings import warn

py_ver = _sys.version_info[:2]

DEFAULT_SERVER_DATE_FORMAT = "%Y-%m-%d"
DEFAULT_SERVER_TIME_FORMAT = "%H:%M:%S"
DEFAULT_SERVER_DATETIME_FORMAT = "%s %s" % (
    DEFAULT_SERVER_DATE_FORMAT,
    DEFAULT_SERVER_TIME_FORMAT)

ALL_RECORDS = [(1,'=',1)]

class MissingRecord(UserWarning):
    "records not found during id search"

def get_records(
        connection, model=None, domain=ALL_RECORDS, fields=[],
        offset=0, limit=None, order=None,
        max_qty=None, ids=None, skip_fields=[],
        context=None,
        ):
    """get records from model

    (connection, model):  (model_obj, None) or (connection, model_str)
    domain:   OpenERP domain for selecting records
    fields:   fields to retrieve (otherwise all)
    max_qty:  raises ValueError if more than max_qty records retrieved

    returns a list of all records found
    """
    context = context or {}
    if model is None:
        # connection is a model object, switch 'em
        model = connection
        connection = model.connection
    else:
        # connection is a connection
        # model is a string, get the real thing
        model = connection.get_model(model)
    # if skip_fields, build actual fields list
    if skip_fields:
        if fields:
            raise ValueError('Cannot specify both fields and skip_fields')
        fields = [f for f in model.fields_get_keys() if f not in skip_fields]
    elif not fields:
        fields = model.fields_get_keys()
    single = False
    result = []
    if not ids:
        ids = model.search(
                domain=domain,
                offset=offset,
                limit=limit or False,
                order=order or False,
                context=context or {},
                )
    if ids:
        if isinstance(ids, (int,long)):
            single = True
            ids = [ids]
        for ids_segment in chunk(ids, 1024):
            segment = model.read(ids_segment, fields=fields, context=context or {})
            if len(segment) != len(ids_segment):
                found = set([r.id for r in segment])
                missing = sorted([i for i in ids_segment if i not in found])
                if missing:
                    warn(
                        'some ids filtered out -- perhaps inactive records?\n%s'
                        % ', '.join([str(m) for m in missing]),
                        UserWarning,
                        stacklevel=2,
                        )
            result.extend(segment)
        if max_qty is not None and len(result) > max_qty:
            raise ValueError('no more than %s records expected for %r, but received %s'
                    % (max_qty, ids or domain, len(result)))
        if single:
            result = result[0]
    return result

class Query(object):

    def __init__(self, model, ids=None, domain=ALL_RECORDS, fields=None, order=None, context=None, _parent=None):
        # fields may be modified (reminder: changes will be seen by caller)
        if context is None:
            context = {}
        if fields is None:
            raise ValueError('FIELDS must be given')
        if ids:
            if domain and domain != ALL_RECORDS:
                raise ValueError('Cannot specify both ids and domain (%r and %r)' % (ids, domain))
            if isinstance(ids, (int,long)):
                ids = [ids]
        elif domain:
            ids = model.search(domain, order=order, context=context)
        # IDs might be zero if there are no matching parent fields
        #
        # save current fields as ordering information since fields itself may be modified
        self.order = fields[:]
        # create a field name to display name mapping
        if _parent is None:
            parent_field, parent_display = '', ''
        else:
            # _parent = (field_name, 'Display Name')
            parent_field = '%s/' % _parent[0]
            parent_display = '%s -> ' % _parent[1]
        self.names = {}.fromkeys([parent_field+n for n in fields])
        #
        main_query = QueryDomain(model, fields, ids)
        self.query = main_query
        self.sub_queries = sub_queries = {}
        many_fields = [f for f in fields if '/' in f]
        if not many_fields:
            field_defs = self.field_defs = model.fields_get(main_query.fields, context=context)
            # save names
            for n, f in field_defs.items():
                self.names[parent_field+n] = parent_display + f['string']
        else:
            unique_fields = []
            for f in fields:
                f = f.split('/')[0]
                if f not in unique_fields:
                    unique_fields.append(f)
            main_query.fields[:] = unique_fields
            nested = defaultdict(list)
            for f in many_fields:
                main_field, sub_field = f.split('/', 1)
                nested[main_field].append(sub_field)
            field_defs = self.field_defs = model.fields_get(main_query.fields, context=context)
            # save names
            for n, f in field_defs.items():
                self.names[parent_field+n] = parent_display + f['string']
            # create sub-queries
            for main_field, sub_fields in nested.items():
                field_def = field_defs[main_field]
                if field_def['type'] not in ('one2many', 'many2many', 'many2one'):
                    raise TypeError('field %r does not link to another table')
                # save name
                self.names[parent_field+main_field] = main_display = parent_display+field_def['string']
                sub_model = model.connection.get_model(field_def['relation'])
                self.sub_queries[main_field] = sub_query = QueryDomain(
                        sub_model,
                        sub_fields,
                        _parent=(main_field, main_display),
                        )
                # if sub_query has it's own query, gather updated field names
                # from it
                if sub_query.query is not None:
                    # XXX: does this ever happen?
                    #    : no - sub_query.query doesn't exist until sub_query
                    #    :      is run
                    pass
                else:
                    # otherwise, we can figure it out ourselves
                    sub_field_defs = sub_model.fields_get(sub_fields, context=context)
                    # save names
                    for n, f in sub_field_defs.items():
                        self.names[parent_field+main_field+'/'+n] = (
                                parent_display + main_display + ' -> ' + f['string']
                                )
        main_query.run()
        # gather ids from main query
        for field, sub_query in sub_queries.items():
            # if many2one then data is an int or False
            # otherwise a (possibly empty) list
            f_type = field_defs[field]['type']
            if f_type == 'many2one':
                for rec in main_query.records:
                    data = rec[field]
                    if data:
                        sub_query.ids.append(data.id)
            elif f_type in ('one2many', 'many2many'):
                for rec in main_query.records:
                    data = rec[field]
                    sub_query.ids.extend(data)
            else:
                raise TypeError('unknown link type for %r: %r' % (field, f_type))
            sub_query.ids = list(set(sub_query.ids))
        # execute subquery and convert linked fields from ids to records
        for field, sub_query in sub_queries.items():
            sub_query.run()
            if sub_query.query is not None:
                self.names.update(sub_query.query.names)
            # if many2one then data is an int or False
            # otherwise a (possibly empty) list
            f_type = field_defs[field]['type']
            if f_type == 'many2one':
                for rec in main_query.records:
                    if rec[field]:
                        rec[field] = sub_query.id_map[rec[field].id]
            elif f_type in ('one2many', 'many2many'):
                for rec in main_query.records:
                    rec[field] = [
                            sub_query.id_map[id]
                            for id in rec[field]
                            ]
        self.records = main_query.records
        self.id_map = main_query.id_map


class QueryDomain(object):

    _cache = dict()       # key: model.model_name, tuple(fields), tuple(ids)
    _cache_key = None

    def __init__(self, model, fields, ids=None, context=None, _parent=None):
        # fields is the /same/ fields object from Query
        self.model = model          # OpenERP model to query
        self.fields = fields        # specific fields to gather
        if ids is None:
            ids = []
        self.ids = ids              # record ids to retrieve
        self.context = context or {}
        self._parent_field = _parent
        self.query = None
        if any(['/' in f for f in self.fields]):
            self.query = True

    def __repr__(self):
        return 'QueryDomain(table=%r, ids=%r, fields=%r)' % (self.model.model_name, self.ids, self.fields)

    @property
    def cache_key(self):
        if self._cache_key is None:
            raise TypeError('run() has not been called yet')
        return self._cache_key

    @property
    def id_map(self):
        return self._cache[self.cache_key][1]

    @property
    def records(self):
        return self._cache[self.cache_key][0]

    def run(self):
        if any(['/' in f for f in self.fields]):
            self.query = Query(
                    self.model,
                    self.ids,
                    None, # domain
                    self.fields,
		    None, # order
                    self.context,
                    _parent=self._parent_field,
                    )
        cache_key = self._cache_key = self.model.model_name, tuple(self.fields), tuple(self.ids)
        if self._cache.get(cache_key) is None:
            records = self.model.read(self.ids, fields=self.fields)
            id_map = dict([
                (r.id, r)
                for r in records
                ])
            # update cache_key as _normalize may have modified list of fields returned
            cache_key = self._cache_key = self.model.model_name, tuple(self.fields), tuple(self.ids)
            self._cache[cache_key] = records, id_map

def _normalize(d, fields=None):
    'recursively convert each dict into a AttrDict'
    # fields may be modified
    res = AttrDict()
    if fields is None:
        fields = d.keys()
    if 'id' in d and 'id' not in fields:
        fields.insert(0, 'id')
    other = set(d.keys()) - set(fields)
    fields.extend(list(other))
    for key in fields:
        value = d[key]
        if isinstance(value, dict):
            res[key] = _normalize(value)
        elif isinstance(value, list) and value and isinstance(value[0], dict) and not isinstance(value[0], AttrDict):
            res[key] = [_normalize(v) for v in value]
        elif (
                isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], (int, long))
            and isinstance(value[1], basestring)
            ):
            res[key] = Many2One(*value)
        else:
            res[key] = value
    return res

class IDEquality(object):
    "compares two objects by id attribute and/or integer value"

    def __eq__(self, other):
        if not self.id:
            return False
        elif isinstance(other, (int, long)):
            return self.id == other
        elif isinstance(other, IDEquality):
            return self.id == other.id
        else:
            return NotImplemented

    def __ne__(self, other):
        if not self.id:
            return False
        elif isinstance(other, (int, long)):
            return self.id != other
        elif isinstance(other, IDEquality):
            return self.id != other.id
        else:
            return NotImplemented

    def __bool__(self):
        return bool(self.id)
    __nonzero__ = __bool__

class Many2One(IDEquality, _aenum.NamedTuple):
    id = 0, "OpenERP id of record"
    name = 1, "_rec_name field of record"


class AttrDict(object):
    """
    allows dictionary lookup using . notation
    allows a default similar to defaultdict
    iterations always ordered by key
    """

    _internal = ['_illegal', '_keys', '_values', '_default', '_ordered']
    _default = None
    _ordered = True
    _illegal = ()
    _values = {}
    _keys = []

    def __init__(self, *args, **kwargs):
        "kwargs is evaluated last"
        if 'default' in kwargs:
            self._default = kwargs.pop('default')
        self._ordered = True
        self._keys = []
        self._values = _values = {}
        self._illegal = _illegal = tuple([attr for attr in dir(_values) if attr[0] != '_'])
        if self._default is None:
            default_factory = lambda : False
        else:
            default_factory = self._default
        for arg in args:
            # first, see if it's a lone string
            if isinstance(arg, basestring):
                arg = [(arg, default_factory())]
            # next, see if it's a mapping
            try:
                new_arg = arg.items()
                if isinstance(arg, OrderedDict):
                    pass
                elif isinstance(arg, AttrDict) and arg._ordered:
                    pass
                else:
                    self._ordered = False
                arg = new_arg
            except (AttributeError, ):
                pass
            # now iterate over it
            for item in arg:
                if isinstance(item, basestring):
                    key, value = item, default_factory()
                else:
                    key, value = item
                if not isinstance(key, basestring):
                    raise ValueError('keys must be strings, but %r is %r' % (key, type(key)))
                if key in _illegal:
                    raise ValueError('%r is a reserved word' % key)
                _values[key] = value
                if key not in self._keys:
                    self._keys.append(key)
        if kwargs:
            self._ordered = False
            self._keys = list(set(self._keys + kwargs.keys()))
            _values.update(kwargs)
        assert set(self._keys) == set(self._values.keys())

    def __contains__(self, key):
        return key in self._values

    def __delitem__(self, name):
        if name[0] == '_':
            raise KeyError("illegal key name: %r" % name)
        if name not in self._values:
            raise KeyError("%s: no such key" % name)
        self._values.pop(name)
        self._keys.remove(name)
        assert set(self._keys) == set(self._values.keys())

    def __delattr__(self, name):
        if name[0] == '_':
            raise AttributeError("illegal key name: %r" % name)
        if name not in self._values:
            raise AttributeError("%s: no such key" % name)
        self._values.pop(name)
        self._keys.remove(name)
        assert set(self._keys) == set(self._values.keys())

    def __eq__(self, other):
        if isinstance(other, AttrDict):
            other = other._values
        elif not isinstance(other, dict):
            return NotImplemented
        return other == self._values

    def __ne__(self, other):
        result = self == other
        if result is NotImplemented:
            return result
        else:
            return not result

    def __getitem__(self, name):
        if name in self._values:
            return self._values[name]
        elif self._default:
            result = self._values[name] = self._default()
            return result
        else:
            raise KeyError("object has no key %r" % name)

    def __getattr__(self, name):
        if name in self._values:
            return self._values[name]
        attr = getattr(self._values, name, None)
        if attr is not None:
            return attr
        elif self._default:
            result = self._values[name] = self._default()
            return result
        else:
            raise AttributeError("object has no attribute %r" % name)

    def __iter__(self):
        if self._ordered:
            return iter(self._keys)
        else:
            return iter(sorted(self._keys))

    def __len__(self):
        return len(self._values)

    def __setitem__(self, name, value):
        if name in self._internal:
            object.__setattr__(self, name, value)
        elif isinstance(name, basestring) and name[0:1] == '_':
            raise KeyError("illegal attribute name: %r" % name)
        elif not isinstance(name, basestring):
            raise ValueError('attribute names must be str, not %r' % type(name))
        else:
            if name not in self._keys:
                self._keys.append(name)
            self._values[name] = value
        assert set(self._keys) == set(self._values.keys())

    def __setattr__(self, name, value):
        if name in self._internal:
            object.__setattr__(self, name, value)
        elif name[0] == '_' or name in self._illegal:
            raise AttributeError("illegal attribute name: %r" % name)
        elif not isinstance(name, basestring):
            raise ValueError('attribute names must be str, not %r' % type(name))
        else:
            if name not in self._keys:
                self._keys.append(name)
            self._values[name] = value

    def __repr__(self):
        if not self:
            return "AttrDict()"
        return "AttrDict([%s])" % ', '.join(["(%r, %r)" % (k, self._values[k]) for k in self.keys()])

    def __str__(self):
        lines = ['{']
        for k, v in self.items():
            if isinstance(v, self.__class__):
                lines.append(' %s = {' % k)
                for line in str(v).split('\n')[1:-1]:
                    lines.append('     %s' % line)
                lines.append('      }')
            else:
                lines.append(' %r:  %r' % (k, v))
        lines.append(' }')
        return '\n'.join(lines)

    def clear(self):
        self._values.clear()
        self._keys[:] = []
        self._ordered = True

    def copy(self):
        result = self.__class__()
        if self._default is not None:
            result._default = self._default
        result._ordered = self._ordered
        result._keys = self._keys[:]
        result._values = self._values.copy()
        result._illegal = self._illegal
        assert set(result._keys) == set(result._values.keys())
        return result

    @classmethod
    def fromkeys(cls, keys, value):
        return cls([(k, value) for k in keys])

    def items(self):
        return [(k, self._values[k]) for k in self.keys()]

    def keys(self):
        if self._ordered:
            return self._keys
        else:
            return sorted(self._keys)

    def pop(self, key, default=None):
        if default is not None:
            value = self._values.pop(key)
        else:
            value = self._values.pop(key, default)
        if key in self._keys:
            self._keys.remove(key)
        return value

    def popitem(self):
        k, v = self._values.popitem()
        self._keys.remove(k)
        return k, v

    def setdefault(self, key, value=None):
        if key not in self._values:
            self._keys.append(key)
        if value is None:
            result = self._values.setdefault(key)
        else:
            result = self._values.setdefault(key, value)
        return result

    def update(self, items, **more_items):
        before = len(self._values)
        self._values.update(items, **more_items)
        after = len(self._values)
        if before != after:
            self._keys = self._values.keys()
            self._ordered = False

    def values(self):
        return [self._values[k] for k in self.keys()]


class EmbeddedNewlineError(ValueError):
    "Embedded newline found in a quoted field"

    def __init__(self, state):
        super(EmbeddedNewlineError, self).__init__()
        self.state = state


class OpenERPcsv(object):
    """csv file in OE format (utf-8, "-encapsulated, comma seperated)
    returns a list of str, bool, float, and int types, one row for each record
    Note: discards first record -- make sure it is the header!"""

    def __init__(self, filename):
        with open(filename) as source:
            self.data = source.readlines()
        self.row = 0        # skip header during iteration
        header = self.header = self._convert_line(self.data[0])
        self.types = []
        known = globals()
        for name in header:
            if '%' in name:
                name, type = name.split('%')
                if type in known:
                    self.types.append(known[type])
                else:
                    func = known['__builtins__'].get(type, None)
                    if func is not None:
                        self.types.append(func)
                    else:
                        raise ValueError("unknown type: %s" % type)
            else:
                self.types.append(None)

    def __iter__(self):
        return self

    def __next__(self):     # just plain 'next' in python 2
        try:
            self.row += 1
            line = self.data[self.row]
        except IndexError:
            raise StopIteration
        items = self._convert_line(line)
        if len(self.types) != len(items):
            raise ValueError('field/header count mismatch on line: %d' % self.row)
        result = []
        for item, type in zip(items, self.types):
            if type is not None:
                result.append(type(item))
            elif item.lower() in ('true','yes','on','t','y'):
                result.append(True)
            elif item.lower() in ('false','no','off','f','n'):
                result.append(False)
            else:
                for type in (int, float, lambda s: str(s.strip('"'))):
                    try:
                        result.append(type(item))
                    except Exception:
                        pass
                    else:
                        break
                else:
                    result.append(None)
        return result
    next = __next__

    @staticmethod
    def _convert_line(line, prev_state=None):
        line = line.strip() + ','
        if prev_state:
            fields = prev_state.fields
            word = prev_state.word
            encap = prev_state.encap
            skip_next = prev_state.skip_next
        else:
            fields = []
            word = []
            encap = False
            skip_next = False
        for i, ch in enumerate(line):
            if skip_next:
                skip_next = False
                continue
            if encap:
                if ch == '"' and line[i+1:i+2] == '"':
                    word.append(ch)
                    skip_next = True
                elif ch =='"' and line[i+1:i+2] in ('', ','):
                    while word[-1] == '\\n':
                        word.pop()
                    word.append(ch)
                    encap = False
                elif ch == '"':
                    raise ValueError(
                            'invalid char following ": <%s> (should be comma or double-quote)\n%r\n%s^'
                            % (ch, line, ' ' * i)
                            )
                else:
                    word.append(ch)
            else:
                if ch == ',':
                    fields.append(''.join(word))
                    word = []
                elif ch == '"':
                    if word: # embedded " are not allowed
                        raise ValueError('embedded quotes not allowed:\n%s\n%s' % (line[:i], line))
                    encap = True
                    word.append(ch)
                else:
                    word.append(ch)
        if encap:
            word.pop()  # discard trailing comma
            if len(word) > 1:  # more than opening quote
                word[-1] = '\\n'
            current_state = AttrDict(fields=fields, word=word, encap=encap, skip_next=skip_next)
            raise EmbeddedNewlineError(state=current_state)
        return fields


class SchroedingerFile(object):
    "loops through lines of filename *if it exists*; deletes file when finished"

    filename = None
    ctxmgr = None

    def __init__(self, filename):
        try:
            self.data = open(filename)
            self.filename = filename
        except IOError:
            self.data = iter([])

    def __enter__(self):
        self.ctxmgr = True
        return self

    def __exit__(self, *args):
        if self.filename:
            try:
                _os.remove(self.filename)
            except OSError:
                pass

    def __iter__(self):
        return self

    def __next__(self):     # just plain 'next' in python 2
        try:
            return next(self.data)
        except StopIteration:
            exc = _sys.exc_info()[1]
            if self.filename and not self.ctxmgr:
                try:
                    _os.remove(self.filename)
                except OSError:
                    pass
            self.data = iter([])
            raise exc
    next = __next__


class UpdateFile(object):
    "loops through lines of filename *if it exists* (no error if missing)"
    def __init__(self, filename):
        try:
            with open(filename) as source:
                self.data = source.readlines()
        except IOError:
            self.data = []
        self.row = -1
    def __iter__(self):
        return self

    def __next__(self):     # just plain 'next' in python 2
        try:
            self.row += 1
            return self.data[self.row]
        except IndexError:
            raise StopIteration
    next = __next__

def chunk(stream, size):
    while stream:
        chunk, stream = stream[:size], stream[size:]
        yield chunk

def PropertyNames(cls):
    for name, thing in cls.__dict__.items():
        if (
                hasattr(thing, '__get__')
                or hasattr(thing, '__set__')
                or hasattr(thing, '__delete__')
                ) and (
                getattr(thing, 'name', False) is None
            ):
            # looks like a descriptor, give it a name
            setattr(thing, 'name', name)
    return cls


class NullType(object):

    __slots__ = ()

    def __new__(cls):
        return cls._null

    if py_ver >= (2, 6):
        __hash__ = None
    else:
        def __hash__(self):
            raise TypeError("unhashable type: 'NullType'")

    if py_ver < (3, 0):
        def __nonzero__(self):
            return False
    else:
        def __bool__(self):
            return False

    def __repr__(self):
        return '<null>'

NullType._null = object.__new__(NullType)
Null = NullType()


class SetOnce(object):
    """
    property that allows setting payload once
    """

    def __init__(self, name=None):
        self.name = name

    def __get__(self, parent, cls):
        if parent is None:
            return self
        elif self.name not in parent.__dict__:
            return Null
        else:
            return parent.__dict__[self.name]

    def __set__(self, parent, value):
        if self.name in parent.__dict__:
            raise AttributeError('attribute %r already set' % (self.name, ))
        elif value is Null:
            return
        else:
            parent.__dict__[self.name] = value
