import logging
import attr

# import openpyxl
from box import Box

# from panopticum.management.commands.django_excel_converter.export.excel_format import TableFormat
# from panopticum.models import User

@attr.s
class ExportableSheet(object):
    sheet_name = attr.ib()
    model = attr.ib()
    data = attr.ib()
    filters = attr.ib()
    formatting = attr.ib()
    dbdata = attr.ib(default=None)

    # @sheet_name.validator
    # def check(self, attribute, value):
    #     if isinstance(value, str):
    #         raise TypeError('%s must be type str' % attribute)

    @classmethod
    def sheet_data(cls, sheet_details):
        if not sheet_details:
            raise ValueError('Sheet_details missing')

        sheet_name = sheet_details.sheet_name if 'sheet_name' in sheet_details else None
        filters = sheet_details.filters if 'filters' in sheet_details else None
        data = sheet_details.dataset.data if 'dataset' in sheet_details and 'data' in sheet_details.dataset else None
        model = sheet_details.dataset.model if 'dataset' in sheet_details and 'model' in sheet_details.dataset else None
        formatting = sheet_details.formatting if 'formatting' in sheet_details else Box(default_box=True)

        missing_fields = [k for k, v in {'sheet_name': sheet_name, 'model': model, 'data': data}.items() if not v]
        if missing_fields:
            raise ValueError('%s missing' % ','.join(missing_fields))

        formatting.col_formatting = data  # We bring column formatting in Table Formatting

        obj =cls(sheet_name=sheet_name, model = model,
                 data=data, filters=filters, formatting=formatting)
        obj._fetch_data()

        return obj
                    # , dbdata=fetch_data())

    def _fetch_data(self):

        def fetch_data(o, data):
            def get_ref_data(o, refs):
                if not o:
                    return None
                return ' - '.join([str(getattr(o, ref_f)) for _,ref_f in refs]) # TODO: HG: for M2M we need to call o.all() and fetch values -- how to do this?

            return [
                (lambda o, f, v:
                            getattr(o, f) if not v.references else get_ref_data(getattr(o, f), v.references))
                    (o, f, v) for (f, v) in data.items()]

        self.dbdata = [list(self.data.keys())]
        self.dbdata.extend([fetch_data(o, self.data)
                        for o in self.model.objects.only(*self.data.keys())])

class Exporter(object):
    # _xlsfile: XlsWriter

    def __init__(self, xlswriter, parser):
        self._xlswriter = xlswriter
        self._parser = parser
        pass

    @staticmethod
    def _create_multientry_str(iterables):
        tmp_str: str = ""
        if isinstance(iterables, list):
            for i in iterables:
                tmp_str += "* " + i + "\n"
        else:  # TODO: HG: Check object type
            for d in iterables.all() if iterables is not None else []:
                tmp_str += "* " + d.name + "\n"
        return tmp_str[:-1]  # remove last character '\n'

    # @staticmethod
    # def _create_email_str(person: User) -> str:
    #     """ Returns formatted Person object in format "firstname lastname <email@address>" """
    #     return (person.first_name
    #             + " "
    #             + person.last_name
    #             + " <"
    #             + person.email
    #             + ">") if person is not None else ""

    def _create_multiemail_str(self, people):
        """ Returns multiple formatted Person objects. It uses _create_email_str() function defined above"""
        tmp_str: str = ""
        for d in people.all() if people is not None else []:
            tmp_str += "* " + self._create_email_str(d) + ";" + "\n"
        return tmp_str[:-2]  # remove last character ','

    def export(self):
        sheet_nms = self._parser.get_sheet_names(export_sequence=True)
        for sheet_nm in sheet_nms:
            sheet = self._parser.get_sheet(sheet_nm)

            exportable_sheet = ExportableSheet.sheet_data(sheet)


            if sheet.filters:
                if sheet.filters.ASC_SORT:
                    asc_sort_columns = sheet.filters.ASC_SORT.columns
                elif sheet.filters.DESC_SORT:
                    desc_sort_columns = sheet.filters.DESC_SORT.columns
                elif sheet.filters.LATEST:
                    # TBD: HG: Handle this case in generic manner
                    pass

            # datadicts = [sheet.dataset.data.keys()]
            # objs = sheet.dataset.model.objects.all()
            # for obj in objs:
            #     datadict = Box(default_box=True)
            #     for col in sheet.dataset.data.keys():
            #         col_data = getattr(obj, col)
            #         ref_data = None
            #         for (ref_cls, ref_field) in sheet.dataset.data[col].references:
            #             ref_data = getattr(col_data, ref_field) if not ref_data else ref_data + ' - ' + getattr(col_data,ref_field)
            #         datadict[col] = ref_data if ref_data else col_data
            #     datadicts.append(datadict)

            def fetch_data(o, data):
                def get_ref_data(o, refs):
                    if not o:
                        return None
                    ref_data = ''
                    for (ref_cls, ref_f) in refs:  # We ignore ref_cls but can be used for further validation purpose
                        ref_data = ref_data + str(getattr(o,
                                                          ref_f)) + ' - '  # TODO: HG: for M2M we need to call o.all() and fetch values -- how to do this?
                    return ref_data[:-3]

                return [
                    (lambda o, f, v: getattr(o, f) if not v.references else get_ref_data(getattr(o, f), v.references))(
                        o, f, v)
                    for (f, v) in data.items()]

            datalst = [list(sheet.dataset.data.keys())]
            datalst.extend([fetch_data(o, sheet.dataset.data) for o in sheet.dataset.model.objects.all()])

            logging.debug('Exporting sheet [%s]' % sheet_nm)
            # self._xlswriter.update_sheet(sheet.formatting, datalst)  # HG: TBD: We are passing 2x2 array here.
            self._xlswriter.update_sheet_1(sheet_nm, datalst)

        # for model_nm in reversed([k for k in mapper.sheets.keys()]):
        #     sheet = mapper.sheets[model_nm]
        #     t_style = get_table_formatter(sheet, mapper.defaults)
        #     table_fmt = TableFormat(sheet.sheet_name, sheet_pos=1)
        #     if 'tabColor' in t_style:
        #         table_fmt = t_style.tabColor
        #     for f in sheet.dataset_obj.data:
        #         c_style = get_column_formatter(f.formatter, mapper.defaults.data)
        #         table_fmt.reg_col(c_style)
        #     self._xlswriter.update_sheet(table_fmt, )  # TODO:HG: Resume from here.
