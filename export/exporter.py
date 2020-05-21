import logging
import attr

# import openpyxl
from box import Box

# from panopticum.management.commands.django_excel_converter.export.excel_format import TableFormat
# from panopticum.models import User
from ..common import Registry, defval_dict, lower
from .excel_format import TableFormat


@attr.s
class ExportableSheet(object):
    name = attr.ib()
    model = attr.ib()
    data = attr.ib()
    filters = attr.ib()
    formatting = attr.ib()

    # Use below information for exporting to Excel file
    columns = attr.ib()
    dbdata = attr.ib(default=None)

    @property
    def sheet_name(self):
        return self.name

    @classmethod
    def from_sheetdata(cls, sheetdata: Box):
        if not sheetdata:
            raise ValueError('Sheet_details missing')

        sheet_nm = defval_dict(sheetdata, 'sheet_name', None)
        filters = defval_dict(sheetdata, 'filters', None)
        data = defval_dict(defval_dict(sheetdata, 'dataset', None), 'data', None)
        model = defval_dict(defval_dict(sheetdata, 'dataset', None), 'model', None)
        # formatting = Box(default_box=True)
        formatting = defval_dict(sheetdata, 'formatting', Box(default_box=True))
        #formatting.col_formatting = lower(data)  # We bring column cf in Table Formatting

        missing_fields = [k for k, v in {'name': sheet_nm, 'model': model, 'data': data}.items() if not v]
        if missing_fields:
            raise ValueError('%s missing' % ','.join(missing_fields))

        # TODO: HG: it would be good idea to do _fetch_data() before and create ExportableSheet with actual data
        obj = cls(name=sheet_nm, model=model, data=data, filters=filters, columns=list(data.keys()),
                  formatting=TableFormat.from_dict(model._meta.model_name, formatting, data))
        obj._fetch_data()  # TODO: HG: Should be done before
        return obj

    def get_formatting(self):
        return self.formatting

    def _fetch_data(self):
        def fetch_data(o, data):

            def _create_multientry_str(iterables):  # TODO: HG:
                tmp_str: str = ""
                if isinstance(iterables, list):
                    for i in iterables:
                        tmp_str += "* " + i + "\n"
                else:  # TODO: HG: Check object type
                    for d in iterables.all() if iterables is not None else []:
                        tmp_str += "* " + d.name + "\n"
                return tmp_str[:-1]  # remove last character '\n'

            def _create_email_str(person) -> str:  # TODO: HG:
                """ Returns formatted Person object in format "firstname lastname <email@address>" """
                return (person.first_name
                        + " "
                        + person.last_name
                        + " <"
                        + person.email
                        + ">") if person is not None else ""

            def _create_multiemail_str(self, people):  # TODO: HG:
                """ Returns multiple formatted Person objects. It uses _create_email_str() function defined above"""
                tmp_str: str = ""
                for d in people.all() if people is not None else []:
                    tmp_str += "* " + self._create_email_str(d) + ";" + "\n"
                return tmp_str[:-2]  # remove last character ','

            def get_ref_data(o, refs):
                if not o:
                    return None
                return ' - '.join([str(getattr(o, ref_f)) for ref_f in refs])

            vals = []
            m2m_fields = [f.name for f in o._meta.many_to_many]
            fkey_fields = [f.name for f in o._meta.fields if f.many_to_one]
            for field, value in data.items():
                if field in m2m_fields:
                    # Check if references is provided by user if not then we use 'pk'
                    ref_fields = ['pk'] if not value.references else [ref for _, ref in value.references]
                    ref_objs = getattr(o, field).only(*ref_fields)
                    # vals.append('\n'.join(['* ' + ' - '.join([str(getattr(ref_obj, ref_f)) for ref_f in ref_fields]) for ref_obj in ref_objs]))
                    vals.append('\n'.join(['* ' + get_ref_data(ref_obj, ref_fields) for ref_obj in ref_objs]))
                elif field in fkey_fields:
                    ref_fields = ['pk'] if not value.references else [ref for _, ref in value.references]
                    vals.append(get_ref_data(getattr(o, field), ref_fields))
                else:
                    vals.append(getattr(o, field))

            return vals

        logging.debug("Fetching data for [%s]" % self.name)
        self.dbdata = []
        dbobjs = None
        if self.filters:
            # TODO: HG: Check for filters and act accordingly.
            # self.model.objects.only(*self.data.keys()).order_by("-order")[0]
            pass
        #else:
        dbobjs = self.model.objects.only(*self.data.keys())

        self.dbdata.extend([fetch_data(o, self.data) for o in dbobjs])


class Exporter(object):
    def __init__(self, xlswriter):
        self._xlswriter = xlswriter
        self.sheets = Box(default_box=True)  # Maintains exportable sheets
        pass

    def export(self):
        sheet_nms = Registry.parser.get_sheet_names(export_sequence=True)
        for sheet_nm in sheet_nms:
            sheet = Registry.parser.get_sheet(sheet_nm)
            es = ExportableSheet.from_sheetdata(sheet)
            self.sheets[sheet_nm] = es
            logging.info('Exporting sheet [%s]' % sheet_nm)
            self._xlswriter.update_sheet(sheet_nm, es.columns, es.dbdata, es.formatting)

    def get_sheet(self, sheet_nm) -> ExportableSheet:
        return defval_dict(self.sheets, sheet_nm, None)

    def get_sheet_by_model(self, model_nm) -> ExportableSheet:
        """
        Returns Exportable sheet by model name
        :param model_nm:
        :return: Exportable Sheet
        """
        matching_sheets = [v for _, v in Registry.exporter.sheets.items() if lower(model_nm) in lower(v.model.__name__)]
        if len(matching_sheets) > 1:
            # not expected, throw exception
            raise ValueError('multiple sheets for model [%s]. Try providing full qualified name.' % (model_nm))
        elif not matching_sheets:
            return None
        else:
            return matching_sheets[0]
