import mimetypes
import os
import re
from datetime import datetime
from decimal import Decimal

from django.utils.timezone import utc

from photonix.photos.models import Camera, Lens, Photo, PhotoFile, Task, Library, Tag, PhotoTag
from photonix.photos.utils.metadata import (PhotoMetadata, parse_datetime, parse_gps_location)


def record_photo(path, library, inotify_event_type=None):
    if type(library) == Library:
        library_id = library.id
    else:
        library_id = str(library)
    try:
        photo_file = PhotoFile.objects.get(path=path)
    except PhotoFile.DoesNotExist:
        photo_file = PhotoFile()

    if inotify_event_type in ['DELETE', 'MOVED_FROM']: 
        if PhotoFile.objects.filter(path=path).exists():
            return delete_photo_record(photo_file)
        else:
            return True

    file_modified_at = datetime.fromtimestamp(os.stat(path).st_mtime, tz=utc)

    if photo_file and photo_file.file_modified_at == file_modified_at:
        return True

    metadata = PhotoMetadata(path)
    date_taken = None
    possible_date_keys = ['Date/Time Original', 'Date Time Original', 'Date/Time', 'Date Time', 'GPS Date/Time', 'Modify Date', 'File Modification Date/Time']
    for date_key in possible_date_keys:
        date_taken = parse_datetime(metadata.get(date_key))
        if date_taken:
            break

    camera = None
    camera_make = metadata.get('Make', '')
    camera_model = metadata.get('Camera Model Name', '')
    if camera_model:
        camera_model = camera_model.replace(camera_make, '').strip()
    if camera_make and camera_model:
        try:
            camera = Camera.objects.get(library_id=library_id, make=camera_make, model=camera_model)
            if date_taken < camera.earliest_photo:
                camera.earliest_photo = date_taken
                camera.save()
            if date_taken > camera.latest_photo:
                camera.latest_photo = date_taken
                camera.save()
        except Camera.DoesNotExist:
            camera = Camera(library_id=library_id, make=camera_make, model=camera_model,
                            earliest_photo=date_taken, latest_photo=date_taken)
            camera.save()

    lens = None
    lens_name = metadata.get('Lens ID')
    if lens_name:
        try:
            lens = Lens.objects.get(name=lens_name)
            if date_taken < lens.earliest_photo:
                lens.earliest_photo = date_taken
                lens.save()
            if date_taken > lens.latest_photo:
                lens.latest_photo = date_taken
                lens.save()
        except Lens.DoesNotExist:
            lens = Lens(library_id=library_id, name=lens_name, earliest_photo=date_taken,
                        latest_photo=date_taken)
            lens.save()

    photo = None
    if date_taken:
        try:
            # TODO: Match on file number/file name as well
            photo = Photo.objects.get(taken_at=date_taken)
        except Photo.DoesNotExist:
            pass

    latitude = None
    longitude = None
    if metadata.get('GPS Position'):
        latitude, longitude = parse_gps_location(metadata.get('GPS Position'))

    iso_speed = None
    if metadata.get('ISO'):
        try:
            iso_speed = int(re.search(r'[0-9]+', metadata.get('ISO')).group(0))
        except AttributeError:
            pass
    if not photo:
        # Save Photo
        aperture = None
        aperturestr = metadata.get('Aperture')
        if aperturestr:
            try:
                aperture = Decimal(aperturestr)
                if aperture.is_infinite():
                    aperture = None
            except:
                pass

        photo = Photo(
            library_id=library_id,
            taken_at=date_taken,
            taken_by=metadata.get('Artist') or None,
            aperture=aperture,
            exposure=metadata.get('Exposure Time') or None,
            iso_speed=iso_speed,
            focal_length=metadata.get('Focal Length') and metadata.get('Focal Length').split(' ', 1)[0] or None,
            flash=metadata.get('Flash') and 'on' in metadata.get('Flash').lower() or False,
            metering_mode=metadata.get('Metering Mode') or None,
            drive_mode=metadata.get('Drive Mode') or None,
            shooting_mode=metadata.get('Shooting Mode') or None,
            camera=camera,
            lens=lens,
            latitude=latitude,
            longitude=longitude,
            altitude=metadata.get('GPS Altitude') and metadata.get('GPS Altitude').split(' ')[0],
            star_rating=metadata.get('Rating')
        )
        photo.save()

        for subject in metadata.get('Subject', '').split(','):
            subject = subject.strip()
            if subject:
                tag = Tag.objects.create(library_id=library_id, name=subject, type="G")
                PhotoTag.objects.create(
                    photo=photo,
                    tag=tag,
                    confidence=1.0
            )
    else:
        for photo_file in photo.files.all():
            if not os.path.exists(photo_file.path):
                photo_file.delete()

    width = metadata.get('Image Width')
    height = metadata.get('Image Height')
    if metadata.get('Orientation') in ['Rotate 90 CW', 'Rotate 270 CCW', 'Rotate 90 CCW', 'Rotate 270 CW']:
        old_width = width
        width = height
        height = old_width

    # Save PhotoFile
    photo_file.photo = photo
    photo_file.path = path
    photo_file.width = width
    photo_file.height = height
    photo_file.mimetype = mimetypes.guess_type(path)[0]
    photo_file.file_modified_at = file_modified_at
    photo_file.bytes = os.stat(path).st_size
    photo_file.preferred = False  # TODO
    photo_file.save()

    # Create task to ensure JPEG version of file exists (used for thumbnailing, analysing etc.)
    Task(
        type='ensure_raw_processed',
        subject_id=photo.id,
        complete_with_children=True,
        library=photo.library
    ).save()

    return photo


def delete_photo_record(photo_file_obj):
    """Delete photo record if photo not exixts on library path."""
    delete_photofile_and_photo_record(photo_file_obj)
    Tag.objects.filter(photo_tags=None).delete()
    Camera.objects.filter(photos=None).delete()
    Lens.objects.filter(photos=None).delete()
    return True


def move_or_rename_photo(photo_old_path, photo_new_path, library_id):
    """Rename a photoFile or change the path while moving photo in child directory."""
    try:
        photo_file = PhotoFile.objects.get(path=photo_old_path)
        photo_file.path = photo_new_path
        photo_file.save()
        return photo_file
    except Exception as e:
        return True


def delete_child_dir_all_photos(directory_path, library_id):
    """When a child directory deleted it delete all the photo records of that directory."""
    for photo_file_obj in PhotoFile.objects.filter(path__startswith=directory_path):
        delete_photofile_and_photo_record(photo_file_obj)
    Tag.objects.filter(photo_tags=None).delete()
    Camera.objects.filter(photos=None).delete()
    Lens.objects.filter(photos=None).delete()
    return True


def delete_photofile_and_photo_record(photo_file_obj):
    """Delete photoFile object with its photo object."""
    photo_obj = photo_file_obj.photo
    photo_file_obj.delete()
    if not photo_obj.files.all():
        photo_obj.delete()
