# django-excel-converter
It works as [django admin command](https://docs.djangoproject.com/en/3.0/howto/custom-management-commands/) 
for importing and exporting large and complex django models from and to excel file respectively.

This project is inspired from [django-excel](https://github.com/pyexcel-webwares/django-excel) . 
This application is developed as a [django admin command](https://docs.djangoproject.com/en/3.0/howto/custom-management-commands/) and hence source code should always be cloned inside `<django_project>/management/commands` with a manual step to invoke the command `django-excel-converter`

## Why yet another django importer/exporter project
While working with panopticum project realized we needed to have excel data in human understandable format for projects with complex and large database schemas.
This project aims to provide application aware import and export functionality between django models and excel.
TODO: Add more specific issues during import.
  
## Features
* Control django models for import/export using configuration file.
* Pick and choose django models, their attributes.
* Declare fields to export in case of foreign dependency. (existing converters will just consider FKEY)
* Simple excel formatting while exporting to excel. Namely - 
  * column wrap length
  * comments at column header level. You can specify - 
    * author
    * height
    * width
  * excel table style
* TODO: Export multiple datasets to same sheet (allow relations).

  
