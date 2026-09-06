#!/usr/bin/env python3
"""helper 写库逻辑本地自测：用模拟 Plex 表结构验证 upsert/列自省/备份。"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import plex_mediainfo_helper as h


def build_fake_db(path: str) -> None:
    """构建一个近似 Plex 结构的模拟数据库，含 media_items/parts/streams。"""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE media_items (
            id INTEGER PRIMARY KEY, width INTEGER, height INTEGER,
            duration INTEGER, bitrate INTEGER, container TEXT,
            video_codec TEXT, audio_codec TEXT, display_aspect_ratio REAL,
            frames_per_second REAL, audio_channels INTEGER
        );
        CREATE TABLE media_parts (
            id INTEGER PRIMARY KEY, media_item_id INTEGER,
            duration INTEGER, size INTEGER, container TEXT, file TEXT
        );
        CREATE TABLE media_streams (
            id INTEGER PRIMARY KEY AUTOINCREMENT, media_item_id INTEGER,
            media_part_id INTEGER, stream_type_id INTEGER, codec TEXT,
            "index" INTEGER, width INTEGER, height INTEGER, bitrate INTEGER,
            channels INTEGER, language TEXT, frame_rate REAL,
            bit_depth INTEGER, sampling_rate INTEGER
        );
        INSERT INTO media_items (id) VALUES (100);
        INSERT INTO media_parts (id, media_item_id, file)
            VALUES (200, 100, '/strm/test.strm');
        """
    )
    conn.commit()
    conn.close()


def main() -> None:
    """执行自测流程并打印结果。"""
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "com.plexapp.plugins.library.db")
    build_fake_db(db)

    # 备份测试
    bak = h.backup_db(db)
    assert os.path.isfile(bak), "备份失败"
    print("备份 OK:", bak)

    payload = {
        "part_id": 200,
        "container": "mkv",
        "duration": 1420000,
        "size": 2147483648,
        "bitrate": 12000,
        "width": 1920,
        "height": 1080,
        "video_codec": "hevc",
        "audio_codec": "flac",
        "frame_rate": 23.976,
        "audio_channels": 6,
        "overwrite_streams": True,
        "streams": [
            {"stream_type": 1, "codec": "hevc", "index": 0, "width": 1920,
             "height": 1080, "bitrate": 12000, "frame_rate": 23.976, "bit_depth": 10},
            {"stream_type": 2, "codec": "flac", "index": 1, "channels": 6,
             "language": "jpn", "sampling_rate": 48000},
            {"stream_type": 3, "codec": "srt", "index": 2, "language": "chi"},
        ],
    }
    res = h.write_media_info(db, payload)
    print("首次写入:", res)
    assert res["success"], res
    assert res["streams_written"] == 3, res

    # 校验写入结果
    conn = sqlite3.connect(db)
    mi = conn.execute(
        "SELECT width,height,video_codec,audio_codec,container FROM media_items WHERE id=100"
    ).fetchone()
    print("media_items:", mi)
    assert mi == (1920, 1080, "hevc", "flac", "mkv"), mi
    ns = conn.execute(
        "SELECT COUNT(*) FROM media_streams WHERE media_part_id=200"
    ).fetchone()[0]
    assert ns == 3, ns

    # 二次写入（overwrite）应先删旧流再写，仍是 3 条
    res2 = h.write_media_info(db, payload)
    print("二次写入:", res2)
    assert res2["streams_deleted"] == 3, res2
    ns2 = conn.execute(
        "SELECT COUNT(*) FROM media_streams WHERE media_part_id=200"
    ).fetchone()[0]
    assert ns2 == 3, ns2
    conn.close()

    print("\n全部自测通过 ✅")


if __name__ == "__main__":
    main()
