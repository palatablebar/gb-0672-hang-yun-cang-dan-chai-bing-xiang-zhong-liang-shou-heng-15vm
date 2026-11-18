import io, json, zipfile
from app.errors import BusinessError

def serialize(result):
    """证据包：任何时候都能导出，用于追回原始采信与补正依据。"""
    if not result.get('manifest') or not result.get('views'):
        raise BusinessError('INCOMPLETE_RUN','批次尚未完成')
    buffer=io.BytesIO()
    corrections=result.get('corrections') or {}
    archive=result.get('archive') or {}
    manifest={**result['manifest'],'revision':result.get('revision',1),'status':result.get('status','待复核'),
              'seal':archive.get('seal'),'seal_status':archive.get('status'),'sealed':archive.get('status')=='可封存'}
    evidence={'counts':result['counts'],'views':result['views'],'quarantine':result['quarantine']}
    if corrections:
        evidence['corrections']={'accepted':corrections.get('accepted',[]),'rejected':corrections.get('rejected',[]),'roots':corrections.get('roots',[])}
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive_file:
        archive_file.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        archive_file.writestr('evidence.json',json.dumps(evidence,ensure_ascii=False,indent=2))
        source=result.get('intake_evidence')
        if source:
            archive_file.writestr('intake_source.json',json.dumps(source,ensure_ascii=False,indent=2))
        if archive.get('status')=='可封存':
            archive_file.writestr('seal.json',json.dumps({
                'seal':archive.get('seal'),
                'roots':[{'id':row['id'],'revision':row['revision'],'source':row['source']}
                         for row in corrections.get('roots',[])],
                'packages':[{'package_id':item['package_id'],'digest':item['digest']}
                            for item in corrections.get('accepted',[])]},ensure_ascii=False,indent=2))
    return buffer.getvalue()
