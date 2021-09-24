from photonix.photos.utils.metadata import PhotoMetadata, get_date_from_filename


from django.conf import settings
from django.core.management.base import BaseCommand

from photonix.photos.models import Photo, PhotoFile
from photonix.web.utils import logger


class Command(BaseCommand):
    help = 'Fix taken date for photos without Metadata from database'


    def delete_whatsapp_photos(self):
        photos = Photo.objects.filter(camera_id__isnull=True)
        for photo in photos:
            logger.debug("Photo: "+str(photo))
            path = str(PhotoFile.objects.get(photo_id=photo))
            logger.debug("PhotoFile: "+path)
            photo.taken_at = get_date_from_filename(path)
            photo.save()

    def handle(self, *args, **options):
        self.delete_whatsapp_photos()

