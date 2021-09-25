from photonix.photos.utils.metadata import PhotoMetadata, parse_datetime, get_date_from_filename


from django.conf import settings
from django.core.management.base import BaseCommand

from photonix.photos.models import Photo, PhotoFile
from photonix.web.utils import logger


class Command(BaseCommand):
    help = 'Fix taken date for photos without Metadata from database'

    def add_arguments(self, parser):
        parser.add_argument('--photoFile', nargs='+', default=[])

    def fix_taken_at(self, paths):
        # photos = Photo.objects.filter(camera_id__isnull=True)
        for path in paths:

            logger.debug("PhotoFile: "+path)
            photoFile = PhotoFile.objects.get(path=path)
            photo = Photo.objects.get(id=photoFile.photo_id)

            metadata = PhotoMetadata(path)
            date_taken = None
            possible_date_keys = ['Create Date', 'Date/Time Original', 'Date Time Original', 'Date/Time', 'Date Time', 'GPS Date/Time', 'Profile Date Time' ]
            for date_key in possible_date_keys:
                date_taken = parse_datetime(metadata.get(date_key))
                if date_taken:
                    break
            if not date_taken:
                date_taken = get_date_from_filename(path)
            if not date_taken:
                date_taken = parse_datetime(metadata.get('File Modification Date/Time')) 


            photo.taken_at = date_taken
            photo.save()

    def handle(self, *args, **options):
        self.fix_taken_at(options['photoFile'])

