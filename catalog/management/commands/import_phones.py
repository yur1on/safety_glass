import csv
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import CompatibilityGroup, PhoneModel, PhoneAlias


class Command(BaseCommand):
    help = "Import phone models + aliases from CSV."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)
        parser.add_argument("--delimiter", type=str, default=",")
        parser.add_argument("--aliases-sep", type=str, default="|")

    @transaction.atomic
    def handle(self, *args, **options):
        path = options["csv_path"]
        delimiter = options["delimiter"]
        aliases_sep = options["aliases_sep"]

        try:
            f = open(path, "r", encoding="utf-8-sig", newline="")
        except OSError as e:
            raise CommandError(f"Cannot open file: {e}")

        created_groups = 0
        created_models = 0
        created_aliases = 0
        updated_models = 0

        with f:
            reader = csv.DictReader(f, delimiter=delimiter)
            required = {"brand", "model_name", "group_name"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise CommandError(f"CSV must contain columns: {sorted(required)}")

            for i, row in enumerate(reader, start=2):
                brand = (row.get("brand") or "").strip()
                model_name = (row.get("model_name") or "").strip()
                group_name = (row.get("group_name") or "").strip()

                if not (brand and model_name and group_name):
                    raise CommandError(f"Row {i}: brand/model_name/group_name required")

                shape_key = (row.get("shape_key") or "").strip()
                notes = (row.get("notes") or "").strip()

                group, g_created = CompatibilityGroup.objects.get_or_create(
                    name=group_name,
                    defaults={"shape_key": shape_key, "notes": notes},
                )
                if g_created:
                    created_groups += 1
                else:
                    changed = False
                    if shape_key and group.shape_key != shape_key:
                        group.shape_key = shape_key
                        changed = True
                    if notes and group.notes != notes:
                        group.notes = notes
                        changed = True
                    if changed:
                        group.save()

                phone, p_created = PhoneModel.objects.get_or_create(
                    brand=brand,
                    model_name=model_name,
                    defaults={"group": group},
                )
                if p_created:
                    created_models += 1
                else:
                    if phone.group_id != group.id:
                        phone.group = group
                        phone.save()
                        updated_models += 1

                aliases_raw = (row.get("aliases") or "").strip()
                if aliases_raw:
                    parts = [a.strip() for a in aliases_raw.split(aliases_sep)]
                    parts = [a for a in parts if a]
                    for a in parts:
                        _, a_created = PhoneAlias.objects.get_or_create(
                            phone_model=phone,
                            alias=a,
                        )
                        if a_created:
                            created_aliases += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Groups +{created_groups}, Models +{created_models} (updated {updated_models}), Aliases +{created_aliases}"
        ))
