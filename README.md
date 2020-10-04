# django-excel-transformer
This project aims at providing a configurable way to export/import Django models to/from excel via configuration file. 

It can be used as a [django admin command](https://docs.djangoproject.com/en/3.0/howto/custom-management-commands/) or integrate with your Django application to allow import and export via browser.

## Why yet another Django importer/exporter project
While working with [Panopticum project](https://github.com/perfguru87/panopticum) realized we needed to have excel data in human understandable format for projects with complex and large database schemas. This tool allows user to control columns to export and choose reference table column in case of FKEYs and M2M. This ensures that exported excel is readable and meaningful without unnecessary numeric FKEYs or M2M keys. 
This project aims to provide application aware import and export functionality between Django models and excel. This is extremely useful when

 1. you want your application users to provide information in excel format instead of them logging to application UI.
 2. you have multiple developers and want to create development environment with partial data set. 

## Installation
There are multiple ways to use this project with your Django application. Below listed 2 methods - 

1. Django management command
2. Import / Export from UI

### Django Management command
To use this project as [django admin command](https://docs.djangoproject.com/en/3.0/howto/custom-management-commands/) follow below instructions:

1. Checkout source code inside `<django_project>/management/commands`. So folder structure looks like as shown below
   <img src="./static/directory-structure-1.png" width="1000">
2. Create `transformer.py` under `<django_project>/management/commands` and copy below code in it.
    ```python
		from django.core.management.base import BaseCommand
		from .django_excel_transformer.export.excel_writter import XlsWriter
		from .django_excel_transformer.export.exporter import Exporter
		from .django_excel_transformer.importer.excel_reader import XlsReader
		from .django_excel_transformer.common import Registry
		from .django_excel_transformer.parser import Parser
		from .django_excel_transformer.importer.importer import Importer
		import logging


		class Command(BaseCommand):
			def add_arguments(self, parser):

				# parser.add_argument('opt', help='import or export', nargs='?', choices=('import','export'))
				parser.add_argument('-c', '--' + 'config', help='Config mapper file (preferred absolute path)', required=True)

				subparsers = parser.add_subparsers(help='Select from importer or exporter parser', dest='opt')

				parser_import = subparsers.add_parser('import', help='Importer options')
				parser_import.add_argument('-x', '--' + 'xls_file', help='XLS file with data for import', required=True)
				parser_import.add_argument('-l', '--' + 'lod', help='level of details',
										   default=0)
				parser_import.add_argument('-r', '--' + 'report_name_prefix', help='report name prefix string e.g. DET',
										   default='DET')
				group = parser_import.add_mutually_exclusive_group()
				group.add_argument('-d',
								   help='dry run. Dont import data in DB. Provides diff between DB and XLS data.',
									dest='dry_run', action='store_true')
				group.add_argument('-u',
								   help='update database with non-conflicting entries (e.g. new xls records)',
								   dest='db_update', action='store_true')
				group.add_argument('-f',
								   help='updates database records',
								   dest='db_force_update', action='store_true')

				parser_export = subparsers.add_parser('export', help='Exporter options')
				parser_export.add_argument('-x', '--' + 'xls_file', help='Export XLS file', required=True)
				parser_export.add_argument('-o', '--overwrite', help='Overwrite existing excel file if exists',
										   action='store_true', default=False)

			def handle(self, *args, **options):
				# Registry maintains common instance for parser, exporter, importer etc. Its used for internal processing.

				debuglevel = {0: logging.CRITICAL, 1: logging.ERROR, 2:logging.INFO, 3:logging.DEBUG}
				logging.basicConfig(
					format='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(funcName)s():%(lineno)d] %(message)s',
					datefmt='%Y-%m-%d:%H:%M:%S',
					level=debuglevel[options['verbosity']])
				Registry.parser = Parser(options['config'])
				Registry.parser.parse() # you can check for errors using parser.errors() and resolve errors in config.yml

				Registry.options = options

				if options['opt'] == 'import':
					Registry.xlreader = XlsReader(options['xls_file'])
					Registry.importer = Importer.from_registry(xls_file = options['xls_file'],
															   lod = options['lod'],
															   report_nm = options['report_name_prefix'],
															   dry_run=options['dry_run'],
															   db_update=options['db_update'],
															   db_force_update=options['db_force_update'])
					Registry.importer.import_sheets()
				else:
					# Now instantiate exporter by providing XlsWriter(path_to_export_xls_file, should_overwrite_yes_no)
					Registry.xlwriter = XlsWriter(options['xls_file'], options['overwrite'])
					Registry.exporter = Exporter()
					Registry.exporter.export()  # wrap this around try-except to handle any exceptions

    ```
3. Now your folder structure should look as shown below
    <img src="./static/directory-structure-2.png" width="1000">

4. You can run Django command as shown below
   Exporter
   ```bash
   cd <django_project_base_folder>
   python ./manage transformer -c config/config.yml -v 3 export -o -x export.xlsx
   ```
   Importer
   ```bash
   cd <django_project_base_folder>
   python ./manage transformer -c config/config.yml -v 3 import -x export.xlsx -u  # -u can be replaced with -d or -f
   ```

5. You can also consider enable logging. In case of errors, this project dumps valuable processing information.

### Import Export from UI
In this option, django-excel-transformer project can be integrated within your Django application with predefined `config` configuration file to import/export from excel file. 

> TODO: provide technical details

## Features
* Control Django models for import/export using configuration file.
* Pick and choose Django models, their attributes.
* Declare fields to export in case of foreign dependency. (existing transformers will just consider FKEY)
* Simple excel formatting while exporting to excel. Below formatting is supported - 
  * column wrap length
  * comments at column header level. You can specify - 
    * author
    * height
    * width
  * excel table style
  * Protected sheets (whole sheet, certain columns only)
  * FKEY fields have data validation enabled if related model is exported as well.
  * Many to many fields exported without data validation enabled.
* Simple Data Filtering support in exporter - Filter conditions supported "or", "and" in context of "exclude" or "include". Filter data is converted as (django Q object)[https://docs.djangoproject.com/en/3.1/ref/models/querysets/#django.db.models.Q]. See config/config.yml for more information and an example. It supports:
  * INCLUDE, EXCLUDE tags in config.yml. Both are exclusive of each other (configure just either of them)
  * "or" & "and" operators
  * only exact match (i.e. only `=` clause supported. so no support for something like `LIKE` clause)
* Allows user to provide nested references in config.yml e.g. ComponentDeploymentModel.version.component.name
* Importer functionality -- Importing XLS data into DB. It supports 
  * dry_run (`-d` flag) provides report comparing DB data vs XLS data.
  * db_force_update (`-f` flag) will override data in DB
  * db_update (`-u` flag) will insert non-conflicting records
  * Generates HTML report based on user provided level of detail flag `lod`


# Technology
1. Python3.6 -- should work with python v3.6 and above. However, its tested with python3.6
2. Djano2.7 -- should work with Django v2.7 and above. However, its tested with django2.7
3. Below python libraries are used
    1. [python-box](https://pypi.org/project/python-box/)
    2. [attrs](https://pypi.org/project/attrs/)
    3. [openpyxl](https://pypi.org/project/openpyxl/) 

## Internals
Application is split into below components with specific role.
1. **`class Parser`** -- responsible to parse configuration config YAML and provide dictionary of exportable sheets, its related dataset and formatting information.
2. **`class Registry`** -- responsible to provide global access to `Parser`, `Exporter`, `Importer` instances. This is used for internal functioning.
3. **`class Exporter`** -- responsible for exporting Django models to the excel file. The dependence models should be exported first and then dependent so that excel sheets have correct data validation. This is achieved using DFS algorithm.
4. **`class Importer`** -- responsible for import excel file into Django model. This class also provides additional functionality like `--dry-run` which can be useful to test excel data against database.
5. **`class XlsWriter`** -- responsible for creating excel file
6. **Excel Formatters** -- These are set of classes assisting Excel Writer and Exporter to format excel. 

<img src="./static/class-diagram.png" width="1000">

There are primarily 2 main inputs to the application -
1. Config YAML file - this is link between Django models and excel workbook (excel file). Please see sample `config\config.yml` file for Panopticum
2. Excel file - (a) exporter case - file will be created, (b) importer case - data will be read from the file.
    1. Each Django model is exported to one or many sheets. Generally 1 model to 1 excel sheet.
    2. FKEY data is controlled via excel data validation
        > TODO: Add GIF explaining this case.
    3. Exported sheets are excel formatted using formatting information if provided in config.YAML

## TODO & Limitations
### TODO
* P1 - Auto tests
* P1 - For export, consider sheet positions in the order they are defined in config YAML file
* P1 - Generic option to exclude specific fields at time of export. e.g. `id`
* P1 - Dedicated classes for Parsed entities. Have a better usage of these various parsed objects within Importer and Exporter classes. This will enable better programmatic way of using library elements.
* P1 - Externalize M2M & FKEY display formats. The characters used for separating fields needs to be escaped
* P2 - Parser errors should point YAML line number
* P2 - Support M2M reverse relationship. e.g. In Panopticum, we would like to export/import [`DatacenterModel`](https://github.com/perfguru87/panopticum/blob/master/panopticum/models.py#L723) within [`ComponentDeploymentModel`](https://github.com/perfguru87/panopticum/blob/master/panopticum/models.py#L680) sheet.
* P2 - Version support (atleast provide version say to Django command with `-v` option)
* P2 - Exporter - Validate if all keys from `index_key` are exported
* P3 - In case of export, if a model is exported to multiple excel sheets (possible due to usage of different filters), then any reference into it should be supported. e.g. [`ComponentVersionModel`](https://github.com/perfguru87/panopticum/blob/master/panopticum/models.py#L365) is exported to 2 sheets `compver_latest` having all latest version and `compver_notlatest` having all versions which aren't part of `compver_latest`, while data within sheet [`ComponentDependencyModel`](https://github.com/perfguru87/panopticum/blob/master/panopticum/models.py#L594) wants to provide excel data validation on [`version`](https://github.com/perfguru87/panopticum/blob/master/panopticum/models.py#L602) field which should refer to either `compver_latest` or `compver_notlatest` 
* P3 - Importer - Parser should have option to skip formatting information 
* P4 - Export multiple datasets to same sheet (allow relations)

### Limitations
* M2M display format is hardcoded. Multiple M2M values are placed in same cell with each entry starting with '* ' and ending EOL
* FKEY display format is hardcoded. Multiple attributes if defined are separated with special string ' - '. Parser assumes attribute value won't have '-' character (BAD ASSUMPTION)   