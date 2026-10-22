from dam.index.driveid import read_drive_id


def test_reads_id(fake_archive):
    p = fake_archive.add("10. Financial/Banks/a.pdf")
    assert read_drive_id(p) == "fake-1"


def test_missing_id_is_none(fake_archive):
    p = fake_archive.add("10. Financial/Banks/a.pdf", drive_id=None)
    assert read_drive_id(p) is None


def test_symlink_not_followed(fake_archive):
    fake_archive.add("10. Financial/Banks/a.pdf")
    link = fake_archive.link("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")
    assert read_drive_id(link) is None
