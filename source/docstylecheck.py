#!/usr/bin/python3
# -*- coding: UTF-8 -*-

import argparse
import glob
import os.path
import re
import subprocess
import sys
import time
import argparse
import random
import webbrowser
try:
    from lxml import etree
except ImportError:
    sys.exit("Could not import from LXML. Is LXML for Python 3 installed?")

__programname__ = "Documentation Style Checker"
__version__ = "0.1.0pre"
__author__ = "Stefan Knorr"
__license__ = "MIT"
__description__ = "checks a given DocBook XML file for stylistic errors"

# global variables
args = None
# terminology data structures
termdataid = None
ignoredpattern = None
accepts = []
patterns = []           # per acceptpattern, add list of list of patterns
contextpatterns = []    # per pattern list, add list of contextpatterns
onepattern = ""         # one long pattern is cheaper than many short ones

# In manglepattern(), only catch patterns that are not literal and are not
# followed by an indicator of a lookahead/lookbehind (?) or are already
# non-capturing groups
parentheses = re.compile( r'(?<!\\)\((?![\?|\:])' )


# TODO: Get rid of the entire "positional arguments" thing that argparse adds
# (self-explanatory anyway). Get rid of "optional arguments" header. Make sure
# least important options (--help, --version) are listed last. Also, I really
# liked being able to use sentences in the parameter descriptions.
def parseargs():
    parser = argparse.ArgumentParser(
        usage = __file__ + " [options] inputfile [outputfile]",
        description = __description__ )
    parser.add_argument('-v', '--version',
        action = 'version',
        version = __programname__ + " " + __version__,
        help = "show version number and exit")
    parser.add_argument( '-s', '--show',
        action = 'store_true',
        default = False,
        help = """show final report in $BROWSER, or default browser if unset; not
            all browsers open report files correctly and for some users, a text
            editor will open; in such cases, set the BROWSER variable with:
            export BROWSER=/MY/FAVORITE/BROWSER ; Chromium or Firefox will both
            do the right thing""" )
    parser.add_argument( '-e', '--errors',
        action = 'store_true',
        default = False,
        help = """output error messages, but do not output warning or
            information messages""" )
    parser.add_argument( '--performance',
        action = 'store_true',
        default = False,
        help = "write some performance measurements to stdout" )
    parser.add_argument( 'inputfile', type=argparse.FileType('r') )
    parser.add_argument( 'outputfile', nargs = "?" )

    return parser.parse_args()

def printcolor( message, type = None ):
    if sys.stdout.isatty():
        if type == 'error':
            print( '\033[0;31m' + message + '\033[0m' )
        else:
            print( '\033[0;32m' + message + '\033[0m' )
    else:
        print( message )

def linenumber( context ):
    return context.context_node.sourceline

def termcheck( context, termfileid, content, contentpretty ):
    # FIXME: Modes: para, title?
    # FIXME: Use fileid to skip creation of data structures
    messages = []

    if content:
        global termdataid
        global ignoredpattern
        global accepts
        global patterns
        global contextpatterns
        global onepattern

        # I get this as a lxml.etree._ElementUnicodeResult, not as a string.
        # For whatever reason, this made is crash happily/semi-randomly when
        # creating messages.
        content = str( content[0] )

        # a calculation:
        #   + the overhead for onepattern is (currently) akin to adding 1 word
        #     to every paragraph
        #   + 30-40 % of paragraphs are skipped because of onepattern
        #   + the paragraphs skipped because of onepattern average at
        #     5-10 words
        #   = worst case: similar time, best case: slight win,
        #     more compliant documentation will tip the scale in our favour
        if not onepattern.search( content ):
            if args.performance:
                print("skipped entire paragraph\n")
            return messages

        # This if/else block should not be necessary (if there is content,
        # there should always also be pretty content, but that depends on the
        # XSLT used for checking). It hopefully won't hurt either.
        if contentpretty:
            contentpretty = str( contentpretty[0] )
        else:
            contentpretty = content

        # FIXME: Get something better than s.split. It is actually quite
        # important to get (most) sentence boundaries in the future. Some
        # existing tokenisers are overzealous, such as the default one from
        # NLTK.
        words = content.split()
        wordposition = 0
        totalwords = len( words )

        if args.performance:
            timestartmatch = time.time()

        skipcount = 0
        for word in words:
            # Idea here: if we previously matched a multi-word pattern, we can
            # simply skip the next few words since they were matched already.
            if skipcount > 0:
                skipcount -= 1
                continue

            if ignoredpattern:
                if ignoredpattern.match( word ):
                    wordposition += 1
                    continue


            # When a pattern already matches on a word, don't try to find more
            # problems with it. (Is that a sane approach? Maybe there are other
            # problems...)
            trynextterm = True

            # Use the *patterns variables defined above to match all patterns
            # over everything.
            acceptposition = 0
            patterngroupposition = 0
            for accept in accepts:
                if trynextterm:
                    acceptword = accept[0]
                    acceptcontext = accept[1]

                    # FIXME: variable names are a bit of a mouthful
                    patterngroupstoaccept = patterns[ acceptposition ]
                    for patterngrouppatterns in patterngroupstoaccept:
                        if not trynextterm:
                            break
                        trycontextpatterns = True
                        matchwords = ""
                        patterngrouppatternposition = 0
                        skipcounttemporary = 0
                        for patterngrouppattern in patterngrouppatterns:
                            patternposition = wordposition + patterngrouppatternposition
                            if ( patternposition < 0 or patternposition > ( totalwords - 1 ) ):
                                trycontextpatterns = False
                                break
                            matchword = patterngrouppattern.match( words[ patternposition ] )
                            if matchword:
                                if not patterngrouppatternposition == 0:
                                    # The first matched pattern should not make
                                    # us skip a word ahead.
                                    skipcounttemporary += 1
                                    matchwords += " "
                                matchwords += matchword.group(0)
                            else:
                                trycontextpatterns = False
                                break
                            patterngrouppatternposition += 1

                        contextwords = []
                        contextpatternstopatterngroup = contextpatterns[ patterngroupposition ]
                        if trycontextpatterns:
                            if contextpatternstopatterngroup[0][0] == None:
                                # easy positive
                                skipcount = skipcounttemporary
                                trynextterm = False
                                line = linenumber ( context )
                                messages.append( termcheckmessage(
                                    acceptword, acceptcontext, matchwords, line,
                                    contentpretty ) )
                            else:
                                for contextpattern in contextpatternstopatterngroup:
                                    if contextpattern[0]:
                                        contextwheres = contextpattern[1]
                                        # positive matching
                                        if not contextpattern[2]:
                                            for contextwhere in contextwheres:
                                                contextposition = None
                                                contextposition = wordposition + contextwhere
                                                if contextwhere > 0:
                                                    # patterngrouppatternposition is at 1,
                                                    # even if there was just one pattern
                                                    contextposition += patterngrouppatternposition - 1
                                                if ( contextposition < 0 or contextposition > ( totalwords - 1 ) ):
                                                    continue
                                                else:
                                                    contextword = contextpattern[0].match( words[ contextposition ] )
                                                    if contextword:
                                                        contextwords.append( True )
                                                        break
                                        # negative matching
                                        else:
                                            contextwordmatch = False
                                            for contextwhere in contextwheres:
                                                contextposition = None
                                                contextposition = wordposition + contextwhere
                                                if contextwhere > 0:
                                                    # patterngrouppatternposition is at 1,
                                                    # even if there was just one pattern
                                                    contextposition += patterngrouppatternposition - 1
                                                if ( contextposition < 0 or contextposition > ( totalwords - 1 ) ):
                                                    continue
                                                else:
                                                    contextword = contextpattern[0].match( words[ contextposition ] )

                                                    if contextword:
                                                        contextwordmatch = True
                                                        break
                                            if not contextwordmatch:
                                                contextwords.append( True )

                            if ( len( contextpatternstopatterngroup ) == len( contextwords )):
                                skipcount = skipcounttemporary
                                trynextterm = False
                                line = linenumber ( context )
                                messages.append( termcheckmessage(
                                    acceptword, acceptcontext, matchwords, line,
                                    contentpretty ) )
                        patterngroupposition += 1
                acceptposition += 1

            wordposition += 1

        if args.performance:
            timeendmatch = time.time()
            timediffmatch = timeendmatch - timestartmatch
            print( """words: %s
time for this para: %s
average time per word: %s\n"""
                % ( str( totalwords ), str( timediffmatch ),
                    str( timediffmatch / (totalwords + .001 ) ) ) )

    return messages

def buildtermdata( context, terms, ignoredwords ):

    global termdataid
    global ignoredpattern
    global accepts
    global patterns
    global contextpatterns
    global onepattern

    if args.performance:
        timestartbuild = time.time()

    termdataid = random.randint(0, 999999999)

    if ignoredwords:
        ignoredpattern = re.compile( manglepattern( ignoredwords[0] ),
            flags = re.I )

    firstpatterngroup = True
    for term in terms:
        acceptwordxpath = term.xpath( 'accept[1]/word[1]' )
        acceptwordxpathcontent = None
        if acceptwordxpath:
            acceptwordxpathcontent = acceptwordxpath[0].text
        # If there is no accepted word, we don't care about its context either
        if acceptwordxpathcontent:
            acceptlist = [ acceptwordxpathcontent ]
            acceptcontextxpath = term.xpath( 'accept[1]/context[1]' )
            if acceptcontextxpath:
                acceptcontextxpathcontent = acceptcontextxpath[0].text
                acceptlist.append( acceptcontextxpathcontent )
            else:
                acceptlist.append( None )

            accepts.append( acceptlist )
        else:
            accepts.append( [ None, None ] )

        patternsofterm = []
        patterngroupxpaths = term.xpath( 'patterngroup' )
        for patterngroupxpath in patterngroupxpaths:
            patternsofpatterngroup = []
            for i in range(1,6):
                patternxpath = patterngroupxpath.xpath( 'pattern%s[1]' % i )
                patternxpathcontent = None
                if patternxpath:
                    patternxpathcontent = manglepattern( patternxpath[0].text )
                if not patternxpathcontent:
                    if i == 1:
                        emptypatternmessage( 'pattern1' )
                    else:
                        break

                pattern = None
                casexpath = getattribute( patternxpath[0], 'case' )
                if casexpath == 'keep':
                    pattern = re.compile( patternxpathcontent )
                else:
                    pattern = re.compile( patternxpathcontent, flags = re.I )
                if i == 1:
                    if not firstpatterngroup:
                        onepattern += '|'
                    else:
                        firstpatterngroup = False
                    # (?: is for non-capturing group since Python only
                    # supports up to 100 named groups.
                    onepattern += '(?:%s)' % patternxpathcontent
                patternsofpatterngroup.append( pattern )

            patternsofterm.append( patternsofpatterngroup )

            contextpatternsofpatterngroup = []
            contextpatternxpaths = patterngroupxpath.xpath( 'contextpattern' )
            if contextpatternxpaths:
                for contextpatternxpath in contextpatternxpaths:
                    contextpatternxpathcontent = manglepattern(
                        contextpatternxpath.text )
                    if not contextpatternxpathcontent:
                        emptypatternmessage( 'contextpattern' )

                    casexpath = getattribute( contextpatternxpath, 'case' )
                    lookxpath = getattribute( contextpatternxpath, 'look' )
                    modexpath = getattribute( contextpatternxpath, 'mode' )
                    matchxpath = getattribute( contextpatternxpath, 'match' )
                    wherexpath = getattribute( contextpatternxpath, 'where' )

                    if casexpath == 'keep':
                        contextpattern = re.compile(
                            contextpatternxpathcontent )
                    else:
                        contextpattern = re.compile(
                            contextpatternxpathcontent, flags = re.I )

                    factor = 1
                    where = []
                    fuzzymode = False
                    negativematch = False

                    if lookxpath == 'before':
                        factor = -1

                    if modexpath == 'fuzzy':
                        fuzzymode = True

                    if matchxpath == 'negative':
                        negativematch = True

                    if wherexpath:
                        if fuzzymode:
                            if int( wherexpath ) > 3:
                                sys.exit("""Terminology: contextpattern in \
fuzzy mode has where value over 3.
Make sure to always use fuzzy mode with where values of 3 or below.""")
                            whererange = range( 1, ( int( wherexpath ) + 1 ) )
                            for i in whererange:
                                where.append( i * factor )
                        else:
                            where = [ ( int( wherexpath ) * factor ) ]
                    else:
                        where = [ ( 1 * factor ) ]

                    contextpatternsofpatterngroup.append(
                        [ contextpattern, where, negativematch ] )
            else:
                contextpatternsofpatterngroup.append( [ None ] )
            contextpatterns.append( contextpatternsofpatterngroup )

        patterns.append( patternsofterm )
    onepattern = re.compile( onepattern, flags = re.I )

    if args.performance:
        timeendbuild = time.time()
        print( "time to build: %s" % str( timeendbuild - timestartbuild ) )
    return termdataid

def manglepattern( pattern ):
    global parentheses

    # Use non-capturing groups since Python only allows for 100 named patterns.
    pattern = parentheses.sub('(?:', pattern)
    pattern = r'\b' + pattern + r'\b'
    return pattern

def getattribute( oldresult, attribute ):
    xpath = oldresult.xpath( '@' + attribute )
    if xpath:
        return xpath[0]
    else:
        return None

def emptypatternmessage( element ):
    sys.exit( """Terminology: There is an empty %s element.
Make sure each %s element in the terminology file(s) contains a pattern."""
        % (element, element) )

def xmlescape( text ):
    escapetable = {
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
        ">": "&gt;",
        "<": "&lt;",
        }
    return "".join(escapetable.get(c,c) for c in text)

def termcheckmessage( acceptword, acceptcontext, word, line, content ):
    # FIXME: shorten content string (in the right place)
    message = None
    content = xmlescape( content )
    if acceptword != None and acceptcontext != None:
        message = etree.XML( """<result>
                <error>In the context of %s, use
                    <quote>%s</quote> instead of <quote>%s</quote>
                    <place><line>%s</line></place>:
                    <quote>%s</quote>
                </error>
            </result>""" % ( acceptcontext, acceptword, word, str(line), content ) )
    elif acceptword != None:
        message = etree.XML( """<result>
                <error>Use <quote>%s</quote> instead of <quote>%s</quote>
                    <place><line>%s</line></place>:
                    <quote>%s</quote>
                </error>
            </result>""" % ( acceptword, word, str(line), content ) )
    else:
        message = etree.XML( """<result>
                <error>Do not use <quote>%s</quote>
                    <place><line>%s</line></place>:
                    <quote>%s</quote>
                </error>
            </result>""" % ( word, str(line), content ) )
    return message


def main():

    timestart = time.time()

    ns = etree.FunctionNamespace(
        'https://www.gitorious.org/style-checker/style-checker' )
    ns.prefix = 'py'
    ns[ 'linenumber' ] = linenumber
    ns[ 'termcheck' ] = termcheck
    ns[ 'buildtermdata' ] = buildtermdata

    location = os.path.dirname( os.path.realpath( __file__ ) )

    global args
    args = parseargs()

    if args.outputfile:
        resultfilename = args.outputfile
        resultpath = os.path.dirname( os.path.realpath( args.outputfile ) )
    else:
        resultfilename = args.inputfile.name
        resultfilename = os.path.basename( os.path.realpath( resultfilename ) )
        resultfilename = re.sub( r'(_bigfile)?\.xml', r'', resultfilename )
        resultfilename = '%s-stylecheck.xml' % resultfilename
        resultpath = os.path.dirname( os.path.realpath( args.inputfile.name ) )

    resultfile = os.path.join( resultpath, resultfilename )

    output = etree.XML(  """<?xml-stylesheet type="text/css" href="%s"?>
                            <results></results>"""
                      % os.path.join( location, 'check.css' ) )
    rootelement = output.xpath( '/results' )

    rootelement[0].append( etree.XML(
            "<results-title>Style Checker Results</results-title>" ) )


    # Checking via XSLT

    parser = etree.XMLParser(   ns_clean = True,
                                remove_pis = False,
                                dtd_validation = False )
    inputfile = etree.parse( args.inputfile, parser )

    for checkfile in glob.glob( os.path.join(   location,
                                                'xsl-checks',
                                                '*.xslc' ) ):
        transform = etree.XSLT( etree.parse( checkfile, parser ) )
        result = transform( inputfile )

        if args.errors:
            # FIXME: The following could presumably also be done without adding
            # a separate stylesheet. Not sure if that would be any more
            # performant.
            errorstylesheet = os.path.join( location, 'errorsonly.xsl' )
            errortransform = etree.XSLT( etree.parse( errorstylesheet, parser ) )
            result = errortransform( result )

        result = result.getroot()

        if not ( len( result.xpath( '/part/result' ) ) ) == 0 :
            rootelement[0].append( result )

    if ( len( output.xpath( '/results/part' ) ) ) == 0:
        rootelement[0].append( etree.XML(
             """<result>
                    <info>No problems detected.</info>
                    <suggestion>Celebrate!</suggestion>
                </result>""" ) )


    output.getroottree().write( resultfile,
                                xml_declaration = True,
                                encoding = 'UTF-8',
                                pretty_print = True )

    if args.show:
        webbrowser.open( resultfile, new = 0 , autoraise = True )

    printcolor( resultfile )
    if args.performance:
        print( "Total: " +  str( time.time() - timestart ) )


if __name__ == "__main__":
    main()
