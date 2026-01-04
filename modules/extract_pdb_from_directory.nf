process extract_pdb_from_directory {
    label 'sge_low'
    container 'domain-annotation-pipeline-pdb-tools'

    input:
    tuple( val(id), path(id_file) )
    val pdb_directory

    output:
    tuple( val(id), path('*.pdb') )

    script:
    """
    awk '{print \$0 ".pdb"}' ${id_file} > pdb_list.txt
    while read -r fname; do
        find ${pdb_directory} -name "\$fname" -type f -exec ln -s {} . \\;
    done < pdb_list.txt
    """
}
