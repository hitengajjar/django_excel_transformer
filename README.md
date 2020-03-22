# django-excel-converter
This project is inspired from (django-excel)[https://github.com/pyexcel-webwares/django-excel] and provide command line utility for importing and exporting django models from and to excel file respectively. This application is developed as a (django admin command)[https://docs.djangoproject.com/en/3.0/howto/custom-management-commands/] and hence source code should always be cloned inside <django_project>/management/commands with a manual step to invoke the command django-excel-converter
## Features
* Control django models for import/export using configuration file.
* Pick and choose django models, their attributes.
* Declare foreign dependencie.
* Simple excel formatting while exporting to excel. Namely - 
  * column wrap length
  * comments at column header level. You can specify - 
    * author
    * height
    * width
  * excel table style

  
