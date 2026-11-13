-- 화면 사진 8장에서 옮긴 쿼리.
-- 원본 편집기 제목: 프로시저 느린 것들_20260721.txt
-- 사진에 나온 select 부터 서브쿼리 닫는 ") x" 까지입니다.
-- 화면 무아레로 아래 몇 글자는 한두 자가 다를 수 있습니다.
--   * 코드 테이블명 tjyujscd, ttkjscd
--   * 제외 대상 id 리터럴
--   * replace(...) 인자는 빈 문자열 두 개로 보였습니다.
--   * adrs_edit_ok 의 세 번째 조건은 jb.jusocd 로 보였습니다.
--   * 산 여부 decode 의 비교값은 '0' 으로 보였습니다.
--   * 본적 도로명 분기의 bjgmchgubun 은 문자 '1', 주소 분기의 b_gmchgubun 은 숫자 1 로 보였습니다.

select
/*+ parallel(8)*/
'0000000000' FACT_EXNT_RCET_NO, -- 사실조사접수번호(매핑된행정기관코드사용함)
Hangkikcd ,
iink as TGPS_IINK, -- 대상자주민등록번호대체키
id TGPS_IINO, -- 대상자주민등록번호
idseq TGPS_IINO_SN, -- 대상자주민등록번호순번
NM TGPS_NM , -- 대상자성명
'1' FACT_EXNT_PROGRS_STUS_CD , -- 사실조사진행상태코드
NULL ATCH_FILE_NO, -- 첨부파일번호
SEDAEJUKWAN HSLD_RLTN_CD , -- 세대주관계코드
HSLD_IINK HSLD_IINK, -- 세대주주민등록번호대체키
sedaejuid HSLD_IINO, -- 세대주주민등록번호
SEDAEJUIDSEQ HSLD_IINO_SN, -- 세대주주민등록번호순번
SEDAEJUNM HSLD_NM , -- 세대주성명
coalesce(
    case
        when pmdm_dr_ok = 1
        then jb_sidonm
            || ' '
            || jb_sikunkunm
            ||
            case
                when i_pmdm = 1
                then ' '
                    || jb_dongnm
            end
            || ' '
            || db_doronm
            ||
            case
                when bjgmchgubun = '1'
                then '지하'
            end
            || ' '
            || bjgmbonbun
            ||
            case
                when length(trim(bjgmbubun)) > 0
                then '-'
                    || bjgmbubun
            end
            ||
            case
                when i_pmdm = 0
                then ' ('
                    || jb_dongnm
                    || ')'
            end
    end,
    case
        when pmdm_num_bad = 1
        then '본적코드(숫자)이상, 주소생성실패'
        else jb_sidonm
            || ' '
            || jb_sikunkunm
            || ' '
            || jb_dongnm
            || ' '
            || decode(jb_dongrinm, NULL,
                NULL,
                jb_dongnm,
                NULL,
                jb_dongrinm
                || ' ')
            || decode(bonjeoksan, NULL,
                NULL,
                '0',
                '산 ')
            || decode(bonjeokbji, NULL,
                NULL,
                to_char(to_number(nvl(bonjeokbji, '0'))))
            || decode(bonjeokho, NULL,
                NULL,
                '-'
                || to_char(to_number(nvl(bonjeokho, '0'))))
    END
) pmdm, -- 등록기준지
case
    when b_drnmcd is null
    then
        case
            when adrs_num_bad = 1
            then '주소코드(숫자)이상: 주소생성실패'
            else ja_sidonm
                || ' '
                || ja_sikunkunm
                || ' '
                || ja_dongnm
                || ' '
                || decode(ja_dongrinm, NULL,
                    NULL,
                    ja_dongnm,
                    NULL,
                    ja_dongrinm
                    || ' ')
                || decode(b_san, NULL,
                    NULL,
                    '0',
                    '산 ')
                || decode(b_bunji, NULL,
                    NULL,
                    to_char(to_number(nvl(b_bunji, '0'))))
                || decode(b_ho, NULL,
                    NULL,
                    '-'
                    || to_char(to_number(nvl(b_ho, '0'))))
                || ' ('
                || decode(b_tong, NULL,
                    NULL,
                    to_char(to_number(nvl(b_tong, '0'))))
                || decode(b_ban, NULL,
                    NULL,
                    '/'
                    || to_char(to_number(nvl(b_ban, '0'))))
                || ') '
                || trim(b_block)
                || ' '
                || ta_tksujsnm
                || decode(b_tksujsdong, NULL,
                    NULL,
                    ''
                    || rtrim(b_tksujsdong)
                    || '동')
                || decode(b_tksujsho, NULL,
                    NULL,
                    ''
                    || rtrim(b_tksujsho)
                    || '호')
        end
    else nvl(
        case
            when adrs_edit_ok = 1
            then ja_sidonm
                || ' '
                || ja_sikunkunm
                ||
                case
                    when i_adrs = 1
                    then ' '
                        || ja_dongnm
                end
                || ' '
                || da_doronm
                ||
                case
                    when b_gmchgubun = 1
                    then '지하'
                end
                || ' '
                || b_gmbonbun
                ||
                case
                    when length(trim(b_gmbubun)) > 0
                    then '-'
                        || b_gmbubun
                end
                ||
                case
                    when length(trim(b_tksujsdong)) > 0 or length(trim(b_tksujsho)) > 0
                    then ','
                end
                ||
                case
                    when length(trim(b_tksujsdong)) > 0
                    then ' '
                        || b_tksujsdong
                        || '동'
                end
                ||
                case
                    when length(trim(b_tksujsfloor)) > 0
                    then ' '
                        || b_tksujsfloor
                        || '층'
                end
                ||
                case
                    when length(trim(b_tksujsho)) > 0
                    then ' '
                        || b_tksujsho
                        || '호'
                end
                ||
                case
                    when i_adrs = 0
                    then ' ('
                        || ja_DONGNM
                        ||
                        case
                            when length(trim(ta_tksujsnm)) > 0
                            then ' '
                                || ta_tksujsnm
                        end
                        || ')'
                    when i_adrs = 1
                    and length(trim(ta_tksujsnm)) > 1
                    then ' ('
                        || ta_tksujsnm
                        || ')'
                end
        end, ' ')
end adrs, -- 등록기준지
TELNO TPNO, -- 전화번호
JUNIPDAY TRRN_DE, -- 전입일자
'3' TGPS_DATA_INPT_MTH_CD, -- 대상자데이터입력방법코드(3-배치에의해자동생성됨)
TO_CHAR(SYSDATE, 'YYYYMMDDHH24MISS') INPT_DT, -- 입력일시
NULL REGT_EMPY_NO -- 입력자사용자번호
,NULL REGT_NM -- 입력자성명
,NULL EXNT_RSUT_RSDE_YN -- 조사결과거주여부
,NULL ONST_VIST_CNFM_YN -- 현장방문확인여부
,NULL TGPS_STMT_CNFM_YN -- 대상자진술확인여부
,NULL REFW_STMT_CNFM_YN -- 참고인진술확인여부
,NULL EXNT_RSUT_INPT_DT -- 조사결과입력일시
,NULL EXNT_RSUT_CN -- 조사결과내용
,NULL EXNT_RSUT_EMPY_NO -- 조사결과사용자번호
,NULL EXNT_RSUT_REGT_NM -- 조사결과입력자성명
,JUSOCHSY LAST_CHNG_RESN_CD
,RESIDENTSTA REGI_SE_CD
,HSLD_RLTN_NM
,LAST_CHNG_RESN_NM
,REGI_SE_NM
,b_DRNMCD NR_CD
,b_jusocd LGDN_CD
,b_TONG
,b_BAN
from ( select
    /*+ parallel(8)*/
    a.Hangkikcd ,
    a.iink ,
    A.id ,
    A.idseq ,
    A.NM ,
    A.SEDAEJUKWAN ,
    a.sedaejuid ,
    a.SEDAEJUIDSEQ ,
    A.TELNO ,
    A.JUNIPDAY ,
    a.JUSOCHSY ,
    a.RESIDENTSTA ,
    a.BONJEOKSAN,
    a.BONJEOKBJI,
    a.BONJEOKHO ,
    a.BJGMCHGUBUN,
    a.BJGMBONBUN,
    a.BJGMBUBUN ,
    b.HSLD_IINK ,
    b.SEDAEJUNM ,
    b.DRNMCD b_DRNMCD,
    b.jusocd b_jusocd,
    b.TONG b_TONG ,
    b.BAN b_BAN ,
    b.san b_san,
    b.bunji b_bunji ,
    b.ho b_ho,
    b.block b_block ,
    b.TKSUJSDONG b_TKSUJSDONG ,
    b.TKSUJSHO b_TKSUJSHO,
    b.TKSUJSFLOOR b_TKSUJSFLOOR,
    b.GMCHGUBUN b_GMCHGUBUN,
    b.GMBONBUN b_GMBONBUN,
    b.GMBUBUN b_GMBUBUN,
    jb.SIDONM jb_SIDONM,
    jb.SIKUNKUNM jb_SIKUNKUNM,
    jb.DONGNM jb_DONGNM,
    jb.DONGRINM jb_DONGRINM,
    db.DORONM db_DORONM,
    ja.SIDONM ja_SIDONM,
    ja.SIKUNKUNM ja_SIKUNKUNM,
    ja.DONGNM ja_DONGNM,
    ja.DONGRINM ja_DONGRINM,
    ta.TKSUJSNM ta_TKSUJSNM,
    da.DORONM da_DORONM,
    NVL(c1.longcdnm, ' ') HSLD_RLTN_NM,
    NVL(c2.longcdnm, ' ') LAST_CHNG_RESN_NM,
    NVL(c3.longcdnm, ' ') REGI_SE_NM,
    case
        when LENGTH(trim(b.drnmcd)) > 0
        and LENGTH(trim(da.doronm)) > 0
        and jb.jusocd is not null
        and da.drnmcd is not null
        then 1
        else 0
    end as adrs_edit_ok,
    case
        when length(trim(a.BJDRNMCD)) > 0
        and length(trim(db.doronm)) > 0
        then 1
        else 0
    end as pmdm_dr_ok,
    case
        when ja.levels != '3'
        then 1
        when ja.levels = '3'
        and ja.type != '3'
        then 1
        else 0
    end as i_adrs,
    case
        when jb.levels != '3'
        then 1
        when jb.levels = '3'
        and jb.type != '3'
        then 1
        else 0
    end as i_pmdm,
    case
        when
            (
                b.bunji is not null
                and validate_conversion(b.bunji as number) = 0
            )
            or
            (
                b.ho is not null
                and validate_conversion(b.ho as number) = 0
            )
            or
            (
                b.tong is not null
                and validate_conversion(b.tong as number) = 0
            )
            or
            (
                b.ban is not null
                and validate_conversion(b.ban as number) = 0
            )
        then 1
        else 0
    end as adrs_num_bad,
    case
        when
            (
                a.bonjeokbji is not null
                and validate_conversion(a.bonjeokbji as number) = 0
            )
            or
            (
                a.bonjeokho is not null
                and validate_conversion(a.bonjeokho as number) = 0
            )
        then 1
        else 0
    end as pmdm_num_bad
FROM TKAI a, -- 개인 기본
    TSD b, -- 세대 기본
    tjyujscd jb,
    tdrnmcd db,
    tjyujscd ja,
    ttkjscd ta,
    tdrnmcd da,
    TSmCd c1,
    TSmCd c2,
    TSmCd c3
WHERE 1 = 1
AND a.SEDAEJUID = b.SEDAEJUID
AND a.SEDAEJUIDSEQ = b.SEDAEJUIDSEQ
and jb.jusocd(+) = a.bonjeokcd
and db.drnmcd(+) = a.BJDRNMCD
and ja.jusocd(+) = b.jusocd
and ta.tksujscd(+) = b.tksujscd
and da.drnmcd(+) = b.drnmcd
and c1.kubuncd(+) = '0004'
and c1.samucd(+) = replace(a.SEDAEJUKWAN, '', '')
and c2.kubuncd(+) = '0003'
and c2.samucd(+) = replace(a.JUSOCHSY, '', '')
and c3.kubuncd(+) = '0001'
and c3.samucd(+) = replace(a.RESIDENTSTA, '', '')
AND A.ID NOT IN
    (
        SELECT ID
        FROM TNISLOG
    )
AND A.RESIDENTSTA IN ('10',
    '11',
    '13',
    '14')
AND a.id <> '7003281NpL0g/aICyxGTIJWJpSJsA=='
AND ROWNUM <= 1000000
) x
